"""Rung 1 of the escalation ladder: act on a control by its accessible label.

Same efferent contract as the other five effectors, so nothing new is needed to gate,
journal, or verify it. What is new is where the act lands: a live window belonging to
whoever is at the machine. Three things follow from that.

**The bound is one window title.** An effector is built for a single window and reads
only that window, so a gate allow for one application cannot travel to another, and a
target naming a second window is refused before anything is touched.

**An invoke is irreversible and has to be verifiable anyway.** A click cannot be
unclicked, so the plan says so and the surface escalates to `needs-human` unless the
operator passes `allow_irreversible`. What a click should produce is the application's
business, so the caller declares the post-condition (a control appears, disappears, or
carries some text) and a plan without one is refused. `set_value` is the reversible
intent: the prior value is read before the write and put back when verification fails.

**Verification re-reads the window.** `uia.ps1` answers `ok` for an invoke it
dispatched, which says nothing about whether the application did anything with it. A
disabled control, a modal that swallowed the click, a handler that threw: all report
`ok`. The instrument's own account of its work is never consulted here, and
`tests/test_false_success.py` holds the case.

This rung is deliberately NOT exposed over MCP (see `registry.NOT_EXPOSED`). It is
reachable by an operator running the surface on their own machine, and reaching it
from off the machine is a separate decision that has not been made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from coherence_membrane.observation import Observation, sha256_hex

from accountable_surface.effector import Plan, RefusedActuation, Verdict
from accountable_surface.uia import (
    SCHEME,
    FakeUiaDriver,
    FakeWindow,
    UiaStructureOrgan,
    canon,
    match_element,
)

# What a caller may intend, and what the gate authorizes for it. Two action kinds
# rather than one, so a grant can carry the reversible intent without the other.
INTENTS = {"invoke": "uia.invoke", "set_value": "uia.set_value"}

# Post-conditions a structural re-read can settle. Nothing else is accepted, because
# a post-condition this rung cannot check is not a post-condition.
EXPECTATIONS = ("appears", "disappears", "value_is")


@dataclass(frozen=True)
class UiaCommand:
    """What the caller hands in. The target names the control; this names the intent.

    `text` belongs to `set_value`. `expect` belongs to `invoke` and is what makes an
    irreversible act verifiable: `{"kind": "appears", "element": "Saved"}`.
    """

    intent: str
    text: str = ""
    expect: dict = field(default_factory=dict)


class UiaEffector:
    """Rung 1: invoke or set a control inside ONE window, on a gate allow bound to the
    exact plan, verified by re-reading the window."""

    name = "uia-effector"

    def __init__(self, driver: Any, window: str, *, max_elements: int = 400) -> None:
        self._driver = driver
        self._window = window
        self._organ = UiaStructureOrgan(driver, max_elements)
        self._planned: dict = {}  # plan.digest -> the previewed command
        self._prior: dict = {}  # plan.digest -> the value read before a set_value

    def bound(self) -> dict:
        """The construction bound a gate allow can never travel outside of. A set of
        one, so a grant naming several windows covers an effector built for any of
        them under the subset rule `bounds.py` already applies to origins."""
        return {"kind": "uia", "windows": [self._window]}

    # --- perception -----------------------------------------------------------

    def perceive(self, target: str) -> Observation:
        """Rung 0, read through this effector's bound. The target's window part is not
        consulted: this reads the window it was built for and no other, so a foreign
        target cannot turn a perception into a way to look at another application."""
        return self._organ.observe(self._window)

    # --- the efferent contract ------------------------------------------------

    def preview(self, target: str, command: UiaCommand, before: Observation | None = None) -> Plan:
        """Resolve the control against the window as it is now and content-address the
        intent. No side effect, and no key or mouse event."""
        action_kind = INTENTS.get(command.intent)
        if action_kind is None:
            raise RefusedActuation(
                f"intent {command.intent!r} is not one this rung serves: {sorted(INTENTS)}")
        _, element = self._parse(target)
        observed = before if before is not None else self.perceive(target)
        chosen = match_element(observed.data.get("elements", []), element)
        if chosen["status"] != "ok":
            raise RefusedActuation(
                f"control {element!r} does not resolve in {self._window!r}: {chosen}")
        if command.intent == "invoke":
            _check_expectation(command.expect)
        content_sha = sha256_hex(canon(_payload(command)))
        digest = "sha256:" + sha256_hex(f"{action_kind}|{target}|{content_sha}".encode("utf-8"))
        self._planned[digest] = command
        return Plan(action_kind, target, content_sha, command.intent == "set_value", True, digest)

    def act(self, plan: Plan, allow_receipt: Any, command: UiaCommand) -> Observation:
        """Touch the window. Refuses without a gate allow bound to this plan, and
        refuses a plan the instrument itself turned down."""
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow -- the effector will not touch the window")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        if self._planned.get(plan.digest) != command:
            raise RefusedActuation("command does not match the previewed (authorized) plan")
        _, element = self._parse(plan.target)
        if command.intent == "set_value":
            prior = self._read_value(element)
            answer = self._driver.run("setvalue", [self._window, element, command.text])
            if answer.get("ok"):
                self._prior[plan.digest] = prior
        else:
            answer = self._driver.run("invoke", [self._window, element])
        if not answer.get("ok"):
            raise RefusedActuation(f"the instrument refused: {answer.get('error') or answer}")
        return self.perceive(plan.target)

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        """Did the WINDOW change? Re-reads it; the instrument's `ok` on the act is not
        evidence and is never consulted here."""
        command = self._planned.get(plan.digest)
        if command is None:
            return Verdict("failed", "no previewed command for this plan")
        if command.intent == "set_value":
            _, element = self._parse(plan.target)
            actual = self._read_value(element)
            if actual == command.text:
                return Verdict("pass", "the control now carries the authorized value")
            return Verdict("failed", f"the control carries {actual!r}, not the authorized value")
        return self._verify_expectation(command.expect, after)

    def rollback(self, plan: Plan) -> Observation:
        """Put back the value read before the write. An invoke has no undo, which is why
        it is planned irreversible and never reaches here."""
        if plan.digest not in self._prior:
            raise RefusedActuation("no prior value recorded for this plan -- the act is irreversible")
        _, element = self._parse(plan.target)
        prior = self._prior[plan.digest]
        self._driver.run("setvalue", [self._window, element, prior if prior is not None else ""])
        return self.perceive(plan.target)

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise, send no verb that
        changes anything, and leave the control's value where it was.

        Probes `type(self)`, so an effector that overrides `act` cannot inherit a green
        selftest for a contract it broke."""
        window = FakeWindow(elements=[{"name": "Field"}], values={"Field": "before"})
        driver = FakeUiaDriver({"probe": window})
        effector = type(self)(driver, "probe")
        command = UiaCommand("set_value", text="after")
        plan = effector.preview(f"{SCHEME}probe/Field", command)
        watermark = len(driver.requests)
        try:
            effector.act(plan, allow_receipt=None, command=command)
            return False  # acted without an allow -- contract violated
        except RefusedActuation:
            pass
        wrote = [r for r in driver.requests[watermark:] if r["verb"] in ("setvalue", "invoke")]
        return not wrote and window.values["Field"] == "before"

    # --- internals ------------------------------------------------------------

    def _verify_expectation(self, expect: dict, after: Observation) -> Verdict:
        elements = after.data.get("elements", [])
        wanted = str(expect.get("element") or "")
        chosen = match_element(elements, wanted)
        kind = expect.get("kind")
        if chosen["status"] == "ambiguous" and kind in ("appears", "disappears"):
            # A label on two controls settles neither presence nor absence. Read as a
            # plain not-found it would call a dialog closed because two are open.
            return Verdict("failed",
                           f"{wanted!r} names more than one control, so the "
                           f"post-condition is not settled: {chosen.get('candidates')}")
        present = chosen["status"] == "ok"
        if kind == "appears":
            if present:
                return Verdict("pass", f"{wanted!r} is present, as the plan expected")
            return Verdict("failed", f"{wanted!r} is absent: the invoke did not land")
        if kind == "disappears":
            if not after.data.get("settles_absence"):
                return Verdict("failed", _unsettled_absence(after))
            if present:
                return Verdict("failed", f"{wanted!r} is still present: the invoke did not land")
            return Verdict("pass", f"{wanted!r} is gone, as the plan expected")
        actual = self._read_value(wanted)
        if actual == expect.get("text"):
            return Verdict("pass", f"{wanted!r} carries the expected text")
        return Verdict("failed", f"{wanted!r} carries {actual!r}, not the expected text")

    def _read_value(self, element: str) -> Any:
        answer = self._driver.run("value", [self._window, element])
        return answer.get("value") if answer.get("ok") else None

    def _parse(self, target: str) -> tuple:
        """Split `uia://<window>/<control>` and refuse a window this effector was not
        built for, whatever a grant says."""
        rest = target[len(SCHEME):] if target.startswith(SCHEME) else ""
        window, _, element = rest.partition("/")
        if not window or not element:
            raise RefusedActuation(
                f"a uia target is {SCHEME}<window>/<control>, not {target!r}")
        if window != self._window:
            raise RefusedActuation(
                f"target window {window!r} is outside the effector's bound: {self._window!r}")
        return window, element


def _payload(command: UiaCommand) -> dict:
    return {"intent": command.intent, "text": command.text, "expect": command.expect}


def _unsettled_absence(after: Observation) -> str:
    """Why a listing cannot say a control is gone.

    Two views read as success without seeing the window. A clipped tree may have cut
    the control. A walk that finished with nothing named cannot tell a window that
    closed from a window that would not open its tree, and that one is the quiet
    case, since nothing about it looks partial.
    """
    if after.data.get("truncated"):
        return "the tree was truncated, so absence is not established"
    return "the tree came back with nothing named, so absence is not established"


def _check_expectation(expect: Any) -> None:
    """An invoke cannot be undone, so it has to be verifiable before it is authorized.
    What a click produces is the application's business and only the caller knows what
    should follow, so the post-condition is declared rather than guessed."""
    kind = expect.get("kind") if isinstance(expect, dict) else None
    if kind not in EXPECTATIONS:
        raise RefusedActuation(
            "an invoke needs a post-condition to be verifiable: "
            f"'kind' one of {list(EXPECTATIONS)}")
    if not str(expect.get("element") or ""):
        raise RefusedActuation("the post-condition needs the control it is about")
    if kind == "value_is" and not isinstance(expect.get("text"), str):
        raise RefusedActuation("a value_is post-condition needs the text to expect")
