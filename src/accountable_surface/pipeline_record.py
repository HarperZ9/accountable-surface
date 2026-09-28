"""Receipt bodies and the messages a step returns to its caller.

Kept apart from the pipeline so the orchestration stays short. Nothing here
reads a field value: the receipt carries an HMAC of it, or nothing when the
policy refused it as a secret.
"""

from __future__ import annotations

from dataclasses import dataclass

from accountable_surface import plan as plan_mod
from accountable_surface import policy
from accountable_surface.detectors import challenge

REDACTION_RULE = "secret-shapes/v1"


@dataclass(frozen=True)
class StepResult:
    """What a step returns: `status` is acted | refused | needs-human | stopped |
    failed, and `verdict` is verified | drift | unverifiable | not-acted."""

    status: str
    verdict: str
    policy: dict
    approval_id: str | None
    message: str
    receipt: dict
    step_id: str | None = None


@dataclass(frozen=True)
class PlanRef:
    """A plan as its steps' receipts name it: the caller's id, and the digest over
    every step, which a receipt carries only as an HMAC under the session salt."""

    plan_id: str | None
    plan_digest: str


@dataclass(frozen=True)
class PlanResult:
    """What run_plan returns: every step that ran, the step it stopped at, the
    steps that never ran, and the plan certificate (the meet over all of them)."""

    plan_id: str | None
    results: list
    stopped_at: str | None
    not_run: list
    certificate: dict


def evidence_summary(evidence, flags=()) -> dict | None:
    if evidence is None:
        return None
    return {"evidence": evidence.digest, "url": evidence.url, "channel": evidence.channel,
            "http_status": evidence.http_status,
            "redaction": {"rule": REDACTION_RULE, "spans": evidence.redactions},
            "detectors": {"challenge": [h.to_dict() for h in challenge.scan(evidence)],
                          "injection": sorted({f.phrase for f in flags})}}


def is_secret(decision) -> bool:
    return any(h["rule"].startswith("R4.") for h in decision.rule_hits)


def plan_hmac(plan: PlanRef | None, receipts) -> str | None:
    return receipts.value_hmac(plan.plan_digest) if plan is not None and plan.plan_digest else None


def step_summary(step, receipts, decision, *, irreversible: bool, plan: PlanRef | None = None) -> dict:
    """The step as a receipt records it. When R4 refused a secret, every digest
    computed over the value (step, plan, post-condition) is withheld too, because
    a digest of a short secret can be reversed by guessing. A step run inside a
    plan names the plan by id and by an HMAC of the plan digest, never the bare
    digest, because the plan digest covers a later step that may be a secret."""
    value = step.args.get("value")
    summary = {"step_id": step.step_id, "action_kind": step.action_kind,
               "target_digest": plan_mod.digest(step.target), "irreversible": irreversible,
               "plan_id": plan.plan_id if plan else None}
    if is_secret(decision):
        return {**summary, "plan_digest": None, "plan_hmac": None, "step_digest": None,
                "post_condition_digest": None, "value_hmac": None,
                "withheld": "R4 refused a secret; no digest over the value is kept"}
    return {**summary, "plan_digest": None if plan else plan_mod.plan_digest([step]),
            "plan_hmac": plan_hmac(plan, receipts), "step_digest": plan_mod.step_digest(step),
            "post_condition_digest": plan_mod.digest(step.post_condition),
            "value_hmac": None if value is None else receipts.value_hmac(str(value))}


def policy_record(decision) -> dict:
    record = decision.to_dict()
    if is_secret(decision):
        record["inputs_digest"] = None  # it covers the step digest, so it goes too
    return record


def reasons(decision) -> list[str]:
    return [f"{h['rule']}: {h['reason']}" for h in decision.rule_hits]


def message_for(outcome: str, decision, *, origin: str, state_path, approval_id=None, command=None) -> str:
    listed = "; ".join(reasons(decision))
    if outcome == "stop":
        if any(h["rule"] == "R3.challenge" for h in decision.rule_hits):
            return (f"stopped: a human check (CAPTCHA or bot challenge) is on screen at {origin}. The target is "
                    f"paused. A person handles the page, then clears the pause with: accountable-surface-authority "
                    f"clear-pause --state {state_path} --target {origin} --reason <why>. ({listed})")
        return f"stopped: {listed}"
    if outcome == "confirm":
        return (f"needs-human: approval {approval_id} is pending. A person approves it in their own terminal with: "
                f"{command} ; then run the step again. ({listed})")
    return f"refused: {listed}"


def act_message(status: str, verdict: str, detail: str) -> str:
    return f"{status}: {verdict} ({detail})"


def schema_refusal(raw, exc, plan: PlanRef | None, policy_digest: str) -> tuple[dict, dict, str | None]:
    """The policy record and receipt body for a malformed step. It may still carry
    a secret value, so nothing digested over the raw step is kept: only its id,
    when it has one."""
    hit = {"rule": "R9.schema", "version": policy.VERSION, "outcome": "refuse", "reason": str(exc)}
    record = policy.PolicyDecision("refuse", [hit], None, None, policy_digest, None).to_dict()
    step_id = raw.get("step_id") if isinstance(raw, dict) else None
    step_id = step_id if isinstance(step_id, str) else None
    body = {"status": "refused", "step": {"step_id": step_id, "plan_id": plan.plan_id if plan else None},
            "policy": record, "before": None, "execution": {"acted": False}, "after": None,
            "verification": {"verdict": "not-acted"}, "approval_pending": None, "rollback": None, "evidence": None,
            "message": f"refused: R9.schema: {exc}"}
    return record, body, step_id
