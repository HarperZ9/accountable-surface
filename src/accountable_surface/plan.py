"""The action plan as data (`accountable-surface.action-plan/v1`).

A plan is JSON a model or a person writes, and it carries no authority. Each step
names an action kind, a structured target (an origin and path, and a control by
accessible name and role or by a stable ref, never a coordinate), its arguments,
and the post-condition the step must produce. `step_digest` covers every field, so
an approval for a step covers the post-condition too: changing what the step must
produce voids the approval.

`effector_content` maps a step onto what the existing effectors already take
(a `WebAction` or a `BrowserAction`), so the pipeline wraps the loop in
`AccountableSurface.actuate` instead of forking it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import urljoin

SCHEMA = "accountable-surface.action-plan/v1"
READ_KINDS = frozenset({"perceive", "find"})
# Post-condition kinds this build can settle, per path. Every other kind in the
# design's vocabulary is refused by R9 until its predicate lands.
CHECKABLE = {
    "web": frozenset({"url_is", "field_value_is", "title_is", "text_present", "element_appears", "element_disappears"}),
    "browser": frozenset({"url_is", "field_value_is", "title_is", "text_present", "element_appears", "element_disappears"}),
}
_COORDINATE_KEYS = frozenset({"x", "y", "coordinate", "coordinates", "point"})
MAX_SETTLE_MS = 60_000  # the longest a readback waits for a late effect


class PlanError(ValueError):
    """A plan step that does not meet the schema. Refused before anything runs."""


@dataclass(frozen=True)
class ActionStep:
    step_id: str
    action_kind: str
    target: dict
    args: dict = field(default_factory=dict)
    post_condition: dict | None = None
    declared_irreversible: bool = False
    cites_observation: str | None = None

    @property
    def origin(self) -> str:
        return str(self.target.get("origin", "")).rstrip("/").lower()

    @property
    def url(self) -> str:
        return self.origin + str(self.target.get("path", "") or "")

    @property
    def control(self) -> dict | None:
        control = self.target.get("control")
        return control if isinstance(control, dict) else None

    @property
    def family(self) -> str:
        return self.action_kind.split(".", 1)[0]

    def to_dict(self) -> dict:
        return {"step_id": self.step_id, "action_kind": self.action_kind, "target": self.target,
                "args": self.args, "post_condition": self.post_condition,
                "declared_irreversible": self.declared_irreversible,
                "cites_observation": self.cites_observation}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value) -> str:
    return "sha256:" + sha256(canonical(value)).hexdigest()


def step_digest(step: ActionStep) -> str:
    return digest(step.to_dict())


def plan_digest(steps) -> str:
    return digest([step_digest(s) for s in steps])


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def step_from_dict(raw: dict) -> ActionStep:
    """Validate one step. Raises PlanError on any shape the schema does not allow."""
    _require(isinstance(raw, dict), "a step must be an object")
    _require(isinstance(raw.get("step_id"), str) and raw["step_id"] != "", "step_id must be a non-empty string")
    _require(isinstance(raw.get("action_kind"), str) and "." in raw["action_kind"], "action_kind must name family.verb")
    target = raw.get("target")
    _require(isinstance(target, dict), "target must be structured, never a free string")
    control = target.get("control")
    if control is not None:
        _require(isinstance(control, dict), "target.control must be an object")
        _require(not (_COORDINATE_KEYS & set(control)), "a control is named by ref or name, never by coordinate")
        _require(bool(control.get("ref") or control.get("name")), "a control needs a ref or a name")
    args = raw.get("args", {})
    _require(isinstance(args, dict), "args must be an object")
    post = raw.get("post_condition")
    _require(post is None or (isinstance(post, dict) and isinstance(post.get("kind"), str)),
             "post_condition must be null or an object with a kind")
    return ActionStep(raw["step_id"], raw["action_kind"], dict(target), dict(args), post,
                      bool(raw.get("declared_irreversible", False)), raw.get("cites_observation"))


def plan_from_document(doc) -> tuple[str | None, list[ActionStep]]:
    """Validate a whole plan before any step runs: the schema string, a plan id,
    and every step. A bare list of steps is accepted as a plan with no id.
    Raises PlanError naming the first step that fails, so step three being
    malformed never lets steps one and two act."""
    if isinstance(doc, list):
        plan_id, raw_steps = None, doc
    else:
        _require(isinstance(doc, dict), "a plan must be an object or a list of steps")
        _require(doc.get("schema") == SCHEMA, f"a plan must declare schema {SCHEMA!r}")
        _require(isinstance(doc.get("plan_id"), str) and doc["plan_id"] != "", "plan_id must be a non-empty string")
        plan_id, raw_steps = doc["plan_id"], doc.get("steps")
    _require(isinstance(raw_steps, list) and raw_steps != [], "a plan needs a non-empty list of steps")
    steps, seen = [], set()
    for index, raw in enumerate(raw_steps):
        label = raw.get("step_id") if isinstance(raw, dict) and isinstance(raw.get("step_id"), str) else f"#{index + 1}"
        try:
            step = step_from_dict(raw)
        except PlanError as exc:
            raise PlanError(f"step {label}: {exc}") from exc
        _require(step.step_id not in seen, f"step {label}: step_id is used twice")
        seen.add(step.step_id)
        steps.append(step)
    return plan_id, steps


def step_ids(doc) -> list[str]:
    """The step ids a plan document names, readable even when it does not validate."""
    raw_steps = doc if isinstance(doc, list) else (doc.get("steps") if isinstance(doc, dict) else None)
    if not isinstance(raw_steps, list):
        return []
    return [r["step_id"] for r in raw_steps if isinstance(r, dict) and isinstance(r.get("step_id"), str)]


def post_condition_problem(step: ActionStep) -> str | None:
    """R9: a state-changing step needs a post-condition the planned readback can
    settle. Returns why not, or None."""
    if step.action_kind.rsplit(".", 1)[-1] in READ_KINDS:
        return None
    if not step.post_condition:
        return "a state-changing step needs a post_condition"
    kind = step.post_condition.get("kind")
    if kind not in CHECKABLE.get(step.family, frozenset()):
        return f"post_condition kind {kind!r} is one the {step.family} readback cannot settle in this build"
    settle = step.post_condition.get("settle_ms", 0)
    if isinstance(settle, bool) or not isinstance(settle, int) or not 0 <= settle <= MAX_SETTLE_MS:
        return f"settle_ms must be a whole number of milliseconds from 0 to {MAX_SETTLE_MS}"
    return None


def effector_content(step: ActionStep):
    """(target string, effector content) for the existing effectors. The effector
    types are imported here, not at module load, so validating or re-deriving a
    plan never loads an effector (the replay no-act test holds this)."""
    from accountable_surface.browser_effector import BrowserAction
    from accountable_surface.web_effector import WebAction

    verb = step.action_kind.rsplit(".", 1)[-1]
    selector = (step.control or {}).get("name", "")
    value = str(step.args.get("value", ""))
    post = step.post_condition or {}
    expected = str(step.args.get("expect_title") or (post.get("value", "") if post.get("kind") == "title_is" else ""))
    if step.family == "web":
        if verb == "submit":
            return step.url, WebAction("submit", url=urljoin(step.url, str(step.args.get("action", ""))), value=expected)
        if verb == "navigate":
            return step.url, WebAction("navigate", url=step.url)
        return step.url, WebAction(verb, url=step.url, selector=selector, value=value)
    if step.family == "browser":
        if verb == "navigate":
            return step.url, BrowserAction("navigate", url=step.url)
        if verb == "click":
            return step.url, BrowserAction("click", url=step.url, selector=selector)
        return step.url, BrowserAction(verb, url=step.url, selector=selector, value=value)
    raise PlanError(f"no effector mapping for {step.action_kind!r} in this build")


def render_public(step: ActionStep) -> dict:
    """What a person or a receipt may see of a step: everything but the value."""
    value = step.args.get("value")
    args = {k: v for k, v in step.args.items() if k != "value"}
    return {"step_id": step.step_id, "action_kind": step.action_kind, "target": step.target,
            "args": args, "value_length": len(str(value)) if value is not None else None,
            "post_condition": {k: v for k, v in (step.post_condition or {}).items() if k != "value"},
            "declared_irreversible": step.declared_irreversible}
