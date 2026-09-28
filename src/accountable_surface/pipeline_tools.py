"""The plugin profile's pipeline tools: one MCP tool per action class, each
running one step (or one plan) through the accountable pipeline.

A tool turns its arguments into an action-plan/v1 step and hands it to
`ActuationPipeline`, which does the rest: the policy check, the gate, the act,
the independent readback, the typed verdict, and the receipt. The tool returns
the verdict, the policy outcome with every rule and reason, the approval id and
the command a person runs when a step is held, and the receipt reference. It
never returns an approval token, and no argument carries a grant, a tier, an
approval, or `allow_irreversible`: those load out of band.

Exposure: `current()` returns the tools the operator configured, and today it
returns `NotExposed` every time, because the registry refuses the web and browser
effectors by name (`registry.NOT_EXPOSED`). The refusal lifts only when the
browser slice is proven live and the operator names the effector in the spec
file. Tests expose the tools on purpose, to a pipeline on a 127.0.0.1 fixture.
"""

from __future__ import annotations

from typing import Any

from accountable_surface import rederive

FAMILY_VERBS = {"web": ("navigate", "fill", "submit"), "browser": ("navigate", "fill", "click")}


class NotExposed:
    """What a pipeline tool answers when the operator has not exposed it."""

    def __init__(self, family: str, reason: str) -> None:
        self.family, self.reason = family, reason

    def call(self, name: str, args: dict) -> tuple[dict, bool]:
        return {"tool": name, "exposed": False,
                "error": f"not exposed: the {self.family} effector is not exposed over MCP ({self.reason})"}, True


def current():
    """The operator-configured pipeline tools, or why there are none."""
    from accountable_surface.registry import NOT_EXPOSED

    family = "web"
    return NotExposed(family, NOT_EXPOSED.get(family, "no operator configuration for the pipeline tools is built"))


def _receipt_ref(receipt: dict) -> dict:
    return {"seq": receipt.get("seq"), "hash": receipt.get("_hash"), "content_hash": receipt.get("content_hash")}


def step_payload(result) -> dict:
    policy = dict(result.policy)
    if any(str(h.get("rule", "")).startswith("R4.") for h in policy.get("rule_hits") or []):
        policy["inputs_digest"] = None  # it covers the refused value
    return {"step_id": result.step_id, "status": result.status, "verdict": result.verdict, "policy": policy,
            "approval_id": result.approval_id, "message": result.message, "receipt": _receipt_ref(result.receipt)}


class PipelineTools:
    def __init__(self, pipeline, approvals, receipts, evidence, *, family: str = "web") -> None:
        if family not in FAMILY_VERBS:
            raise ValueError(f"unknown effector family {family!r}")
        self.pipeline, self.approvals, self.receipts, self.evidence = pipeline, approvals, receipts, evidence
        self.family = family

    def call(self, name: str, args: dict) -> tuple[Any, bool]:
        handler = getattr(self, "_" + name, None)
        if handler is None:
            return {"error": f"unknown pipeline tool {name!r}"}, True
        return handler(args)

    # --- write tools -----------------------------------------------------------

    def _step(self, verb: str, args: dict, *, target_control=True, post=None, extra=None) -> dict:
        """The step a tool call stands for. Its id is the verb, so the same call
        made again is the same step, and an approval for it still matches."""
        target = {"origin": args["origin"], "path": args["path"]}
        if target_control:
            target["control"] = args["control"]
        return {"step_id": verb, "action_kind": f"{self.family}.{verb}", "target": target,
                "args": extra or {}, "post_condition": args.get("post_condition") or post}

    def _run(self, step: dict) -> tuple[dict, bool]:
        verb = step["action_kind"].rsplit(".", 1)[-1]
        if verb not in FAMILY_VERBS[self.family]:
            return {"error": f"{step['action_kind']} is not something the {self.family} effector can do"}, True
        return step_payload(self.pipeline.run_step(step)), False

    def _browser_navigate(self, args):
        url = str(args["origin"]).rstrip("/") + str(args["path"])
        return self._run(self._step("navigate", args, target_control=False, post={"kind": "url_is", "value": url}))

    def _browser_fill(self, args):
        post = {"kind": "field_value_is", "control": args["control"], "value": args["value"]}
        return self._run(self._step("fill", args, post=post, extra={"value": args["value"]}))

    def _browser_click(self, args):
        return self._run(self._step("click", args))

    def _browser_submit(self, args):
        if self.family == "browser":
            step = self._step("click", args)
            step["declared_irreversible"] = True
            return self._run(step)
        extra = {"action": args.get("action", ""), "expect_title": args.get("expect_title", "")}
        return self._run(self._step("submit", args, extra=extra))

    def _run_plan(self, args):
        result = self.pipeline.run_plan(args["plan"])
        return {"plan_id": result.plan_id, "steps": [step_payload(r) for r in result.results],
                "stopped_at": result.stopped_at, "not_run": result.not_run,
                "certificate": result.certificate}, False

    def _withdraw_approval(self, args):
        return {"approval_id": args["approval_id"], "withdrawn": self.approvals.withdraw(str(args["approval_id"]))}, False

    # --- read tools ------------------------------------------------------------

    def _check_plan(self, args):
        doc = args["plan"]
        steps = doc.get("steps") if isinstance(doc, dict) and "steps" in doc else [doc]
        if not isinstance(steps, list):
            return {"error": "plan.steps must be a list"}, True
        return {"steps": [self.pipeline.check_step(s) for s in steps]}, False

    def _approvals_pending(self, args):
        return {"pending": self.approvals.pending()}, False

    def _receipt_verify(self, args):
        level = args.get("level") or "verdict"
        root = self.evidence.root if self.evidence is not None else self.receipts.path.parent / "no-evidence-store"
        return rederive.rederive(self.receipts.path, root, level=level), False

    def _journal(self, args):
        surface = self.pipeline.surface
        verdict = surface.verify_journal()
        return {"chain_ok": verdict["chain_ok"], "tamper_count": verdict["tamper_count"],
                "entries": [entry.to_dict() for entry in surface.journal]}, False
