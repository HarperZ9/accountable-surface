"""The accountable actuation pipeline: every act runs the same stages.

    S1 plan      the step is validated and digested                  (plan.py)
    S2 before    the driver's own state, plus an independent read of the page
                 the driver is on, with secret shapes redacted        (page_evidence.py)
    S3 policy    pass | confirm | refuse | stop                       (policy.py, pure)
    S4 gate      bound check + proof-surface gate, bound to the S2 page digest
    S5 act       the existing effector, through AccountableSurface.actuate
    S6 after     the driver's after-snapshot, plus a separate read where the
                 post-condition names one or the step navigated
    S7 verify    predicate + effector verify, met; a challenge after the act
                 makes the step unverifiable and stops it              (predicates.py)
    S9 receipt   one hash-chained receipt for every step, acted or not

The pipeline wraps the loop in `AccountableSurface.actuate`; it does not fork it.
It never reads a page the driver is not already on, it reads nothing on a paused
target, and it retries nothing: a stop is final until a person clears it.
`allow_irreversible` is passed true only when S3 consumed a live approval for
this exact step, so a blanket grant flag never stands in for a person.

Not built here yet: rollback on a predicate drift (the surface still rolls back
a failed effector verify), the content-addressed evidence store, and the
browser and desktop drivers proven live.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any

from accountable_surface import plan as plan_mod
from accountable_surface import policy, predicates
from accountable_surface.certify import plan_certificate
from accountable_surface.detectors import challenge, secrets
from accountable_surface.effector import RefusedActuation
from accountable_surface import evidence as evidence_mod
from accountable_surface.evidence import redact_snapshot
from accountable_surface.page_evidence import blank, capture, from_snapshot
from accountable_surface.pipeline_record import (
    PlanRef, PlanResult, StepResult, act_message, evidence_summary, message_for, plan_hmac,
    policy_record, reasons, schema_refusal, step_summary,
)

IDENTITY_FIELDS = {"web-effector": "page_digest", "browser-effector": "page_digest",
                   "fs-effector": "sha256", "api-effector": "sha256"}


def default_reader(url: str):
    return capture(url, redactor=secrets.redact)


class _IrreversibleView:
    """Delegates every method and lowers the plan's reversible bit, so an R7 hit
    needs `allow_irreversible` at the surface (the effector plans clicks reversible)."""

    def __init__(self, effector: Any) -> None:
        self._effector = effector

    def __getattr__(self, name: str) -> Any:
        return getattr(self._effector, name)

    def preview(self, target, content, before=None):
        return replace(self._effector.preview(target, content, before), reversible=False)


@dataclass
class _Context:
    step: Any
    target: str
    content: Any
    reversible: bool
    now: str
    paused: frozenset
    before: Any = None
    effector_before: Any = None
    approval: dict | None = None
    plan: PlanRef | None = None
    refs: dict | None = None


def _challenged(snapshot, reader) -> bool:
    return bool(challenge.scan(from_snapshot(snapshot)) or (reader and challenge.scan(reader)))


def _has(decision, rule: str) -> bool:
    return any(h["rule"] == rule for h in decision.rule_hits)


class ActuationPipeline:
    def __init__(self, surface, effector, *, grant, approvals, receipts, reader=None, config=None,
                 evidence=None) -> None:
        self.surface, self.effector, self.grant = surface, effector, grant
        self.approvals, self.receipts = approvals, receipts
        self.reader = reader or default_reader
        self.config = config
        self.evidence = evidence  # an EvidenceStore; without one, receipts re-derive only at L0

    def run_plan(self, doc) -> PlanResult:
        """Validate the whole plan, then run its steps in order and stop at the
        first one that is not verified. The certificate is the meet over every
        step, the ones that never ran included."""
        ids = plan_mod.step_ids(doc)
        plan_id = doc.get("plan_id") if isinstance(doc, dict) and isinstance(doc.get("plan_id"), str) else None
        try:
            plan_id, steps = plan_mod.plan_from_document(doc)
        except plan_mod.PlanError as exc:
            refusal = self._schema_refusal({"step_id": None}, exc, plan=PlanRef(plan_id, ""))
            return PlanResult(plan_id, [refusal], None, ids, plan_certificate([], ids).to_dict())
        ref = PlanRef(plan_id, plan_mod.plan_digest(steps))
        results = []
        for step in steps:
            results.append(self.run_step(step, plan=ref))
            if results[-1].verdict != "verified":
                break
        not_run = [s.step_id for s in steps[len(results):]]
        stopped = results[-1].step_id if results[-1].verdict != "verified" else None
        cert = plan_certificate([(r.step_id, r.verdict) for r in results], not_run)
        return PlanResult(plan_id, results, stopped, not_run, cert.to_dict())

    def check_step(self, raw) -> dict:
        """S1 to S3 for one step, advisory: reads the page the step names and
        runs the policy check, and writes nothing (no pending approval, no
        evidence, no receipt) and never acts."""
        try:
            step = raw if isinstance(raw, plan_mod.ActionStep) else plan_mod.step_from_dict(raw)
            ctx = self._prepare(step)
        except (plan_mod.PlanError, RefusedActuation) as exc:
            record, _, step_id = schema_refusal(raw, exc, None, policy.policy_digest(self.config))
            return {"step_id": step_id, **record}
        decision = policy.decide(step, ctx.before, grant=self.grant, approval=ctx.approval, paused=ctx.paused,
                                 now=ctx.now, plan_reversible=ctx.reversible, config=self.config)
        return {"step_id": step.step_id, **policy_record(decision)}

    def run_step(self, raw, *, plan: PlanRef | None = None) -> StepResult:
        try:
            step = raw if isinstance(raw, plan_mod.ActionStep) else plan_mod.step_from_dict(raw)
            ctx = self._prepare(step)
        except (plan_mod.PlanError, RefusedActuation) as exc:
            return self._schema_refusal(raw, exc, plan=plan)
        ctx.plan = plan
        decision = policy.decide(step, ctx.before, grant=self.grant, approval=ctx.approval, paused=ctx.paused,
                                 now=ctx.now, plan_reversible=ctx.reversible, config=self.config)
        ctx.refs = evidence_mod.store_inputs(self.evidence, ctx, decision, grant=self.grant, config=self.config)
        if decision.outcome == "stop":
            return self._stop(ctx, decision)
        if decision.outcome == "refuse":
            msg = message_for("refuse", decision, origin=step.origin, state_path=self.approvals.path)
            return self._record(ctx, decision, "refused", "not-acted", msg)
        if decision.outcome == "confirm":
            return self._hold(ctx, decision)
        return self._act(ctx, decision)

    # --- S1 and S2 -------------------------------------------------------------

    def _prepare(self, step) -> _Context:
        target, content = plan_mod.effector_content(step)
        reversible = self.effector.preview(target, content, None).reversible
        ctx = _Context(step, target, content, reversible, self.approvals.now(), self.approvals.paused_targets())
        if policy.target_key(step) in ctx.paused:
            return ctx  # nothing is read on a paused target
        ctx.effector_before = self.effector.perceive(target)
        ctx.before = self._read_before(step, ctx.effector_before)
        if ctx.before is not None:
            ctx.approval = self.approvals.live_for(plan_mod.step_digest(step), ctx.before.digest)
        return ctx

    def _read(self, url: str | None):
        if not url:
            return None
        try:
            return self.reader(url)
        except Exception:  # noqa: BLE001 - an unreadable page is recorded as no evidence
            return None

    def _read_before(self, step, effector_before):
        current = str(effector_before.data.get("url") or "")
        if step.action_kind.endswith(".navigate"):
            return self._read(current) if current.startswith(("http://", "https://")) else blank(current)
        if current.rstrip("/") != step.url.rstrip("/"):
            return None  # never read a page the driver is not on
        return self._read(step.url)

    # --- outcomes --------------------------------------------------------------

    def _stop(self, ctx: _Context, decision) -> StepResult:
        if decision.pause and ctx.before is not None:
            self.approvals.pause(policy.target_key(ctx.step), "R3.challenge", ctx.before.digest)
        msg = message_for("stop", decision, origin=ctx.step.origin, state_path=self.approvals.path)
        return self._record(ctx, decision, "stopped", "not-acted", msg)

    def _hold(self, ctx: _Context, decision) -> StepResult:
        step = ctx.step
        rendering = {**plan_mod.render_public(step), "reasons": reasons(decision), "page": ctx.before.url,
                     "flagged_spans": [f.span for f in decision.injection_flags] if _has(decision, "R8.echo") else []}
        plan_ref = plan_hmac(ctx.plan, self.receipts) or plan_mod.plan_digest([step])
        approval_id = self.approvals.request(plan_mod.step_digest(step), plan_ref, ctx.before.digest, rendering)
        command = f"accountable-surface-authority approve --state {self.approvals.path} --approval-id {approval_id}"
        msg = message_for("confirm", decision, origin=step.origin, state_path=self.approvals.path,
                          approval_id=approval_id, command=command)
        return self._record(ctx, decision, "needs-human", "not-acted", msg, approval_id=approval_id)

    def _act(self, ctx: _Context, decision) -> StepResult:
        step = ctx.step
        if decision.approval is not None and not self.approvals.consume(
                decision.approval["approval_id"], plan_mod.step_digest(step), ctx.before.digest):
            return self._hold(ctx, replace(decision, outcome="confirm", approval=None))
        effector = _IrreversibleView(self.effector) if _has(decision, "R7.irreversible") else self.effector
        field = IDENTITY_FIELDS.get(ctx.effector_before.organ)
        expected = ctx.effector_before.data.get(field) if field else None
        try:
            outcome, error = self.surface.actuate(
                effector, target=ctx.target, content=ctx.content, authorization=self.grant,
                expected_digest=expected, allow_irreversible=decision.approval is not None), None
        except Exception as exc:  # noqa: BLE001 - a driver error mid-act is recorded, never retried
            outcome, error = None, secrets.redact(f"{type(exc).__name__}: {exc}")[0][:300]
        return self._verify(ctx, decision, outcome, error, bound=expected is not None)

    # --- S6, S7, S9 ------------------------------------------------------------

    def _read_after(self, ctx: _Context):
        snapshot = redact_snapshot(self.effector.perceive(ctx.target).data)[0]
        path = (ctx.step.post_condition or {}).get("path")
        url = ctx.step.origin + str(path) if path else (ctx.step.url if ctx.step.action_kind.endswith(".navigate") else None)
        return snapshot, self._read(url)

    def _after(self, ctx: _Context, acted: bool):
        """The after read. With settle_ms, re-read until the post-condition holds, a
        forbidden condition or a human check shows, or the time runs out; the last
        flag says it ran out. Never waits on a page showing a human check."""
        post = ctx.step.post_condition or {}
        deadline = time.monotonic() + int(post.get("settle_ms") or 0) / 1000
        while True:
            snapshot, reader = self._read_after(ctx)
            if not acted or not post.get("settle_ms"):
                return snapshot, reader, False
            done = predicates.check(post, driver_after=snapshot, reader_after=reader)[0] == "verified"
            if done or predicates.forbidden_present(post, reader) or _challenged(snapshot, reader):
                return snapshot, reader, False
            if time.monotonic() >= deadline:
                return snapshot, reader, True
            time.sleep(0.1)

    def _verify(self, ctx: _Context, decision, outcome, error, *, bound: bool) -> StepResult:
        acted = bool(outcome and outcome.acted)
        snapshot, reader, timed_out = self._after(ctx, acted)
        evidence_mod.store_after(self.evidence, ctx.refs, snapshot=snapshot, reader=reader, outcome=outcome,
                                 error=error, timed_out=timed_out)
        after_ev = reader or from_snapshot(snapshot)
        challenged = _challenged(snapshot, reader)
        verification = {"verdict": "not-acted", "effector_verify": outcome.verdict if outcome else None}
        if acted:
            pred, detail, independence = predicates.check(ctx.step.post_condition, driver_after=snapshot,
                                                          reader_after=reader, timed_out=timed_out)
            verdict = predicates.meet(["verified" if outcome.verified else "drift", pred])
            verification.update(predicate=f"{ctx.step.post_condition.get('kind')}/{predicates.VERSION}",
                                detail=detail, independence=independence)
        else:
            verdict, detail = ("unverifiable" if error or challenged else "not-acted"), error or "; ".join(outcome.reasons)
        if challenged:
            verdict = "unverifiable"
            self.approvals.pause(policy.target_key(ctx.step), "R3.challenge-after", after_ev.digest)
            detail = "a human check appeared after the act; the target is paused"
        verification["verdict"] = verdict
        status = "stopped" if challenged else ("acted" if acted else ("failed" if error else "refused"))
        execution = {"acted": acted, "error": error, "precondition_bound": bound,
                     "gate_decision": outcome.decision if outcome else None,
                     "surface_verdict": outcome.verdict if outcome else None,
                     "rolled_back": outcome.rolled_back if outcome else False,
                     "certificate": outcome.certificate if outcome else None}
        after = {**evidence_summary(after_ev), "driver_url": snapshot.get("url")}
        return self._record(ctx, decision, status, verdict, act_message(status, verdict, detail),
                            execution=execution, after=after, verification=verification)

    def _record(self, ctx, decision, status, verdict, message, *, approval_id=None, execution=None,
                after=None, verification=None) -> StepResult:
        body = {"status": status,
                "step": step_summary(ctx.step, self.receipts, decision, irreversible=_has(decision, "R7.irreversible"),
                                     plan=ctx.plan),
                "policy": policy_record(decision), "before": evidence_summary(ctx.before, decision.injection_flags),
                "execution": execution or {"acted": False}, "after": after,
                "verification": verification or {"verdict": verdict}, "approval_pending": approval_id,
                "evidence": ctx.refs, "message": message}
        return StepResult(status, verdict, decision.to_dict(), approval_id, message, self.receipts.emit(body),
                          ctx.step.step_id)

    def _schema_refusal(self, raw, exc, *, plan: PlanRef | None = None) -> StepResult:
        record, body, step_id = schema_refusal(raw, exc, plan, policy.policy_digest(self.config))
        return StepResult("refused", "not-acted", record, None, body["message"], self.receipts.emit(body), step_id)
