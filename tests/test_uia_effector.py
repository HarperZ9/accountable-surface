"""Rung 1: acting on a control by its accessible label, and everything refused first.

The rung below is in `test_uia_structure.py`, and the window facet of `allowed_bounds`
is held in `test_effector_bounds.py` beside the other bound facets. What is under
pressure here is the gap between dispatching an act and having done it: the instrument
reports `ok` for work the application ignored, so every case ends at what a fresh read
of the window says.
"""

from __future__ import annotations

import json

import pytest

from accountable_surface.effector import RefusedActuation
from accountable_surface.registry import load_effectors
from accountable_surface.surface import AccountableSurface
from accountable_surface.uia import SCHEME, FakeUiaDriver, FakeWindow
from accountable_surface.uia_effector import UiaCommand, UiaEffector

WINDOW = "Notepad"
FIELD = f"{SCHEME}{WINDOW}/Field"
SAVE = f"{SCHEME}{WINDOW}/Save"
SAVED = {"kind": "appears", "element": "Saved"}


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-uia-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "uia-caller"},
        "intent": "uia rung test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _window(**kwargs):
    base = {"elements": [{"name": "Field", "type": "Edit", "automationId": "field-1"},
                         {"name": "Save", "type": "Button", "automationId": "save-1"}],
            "values": {"Field": "before"}}
    base.update(kwargs)
    return FakeWindow(**base)


def _driver(window=None, **kwargs):
    return FakeUiaDriver({WINDOW: window or _window()}, **kwargs)


def _act(effector, target, command, actions, **kwargs):
    return AccountableSurface().actuate(effector, target=target, content=command,
                                        authorization=_grant(actions), **kwargs)


# --- what is refused before anything is touched ------------------------------


def test_a_target_naming_another_window_is_refused():
    driver = _driver()
    effector = UiaEffector(driver, WINDOW)
    with pytest.raises(RefusedActuation, match="outside the effector's bound"):
        effector.preview(f"{SCHEME}Calculator/Field", UiaCommand("set_value", text="x"))
    assert not [r for r in driver.requests if r["args"][0] != WINDOW]


def test_a_perception_never_reads_a_window_the_effector_was_not_built_for():
    """`perceive` is called by the surface with the caller's target before anything is
    gated, so it reads the bound window and ignores what the target names. Otherwise a
    foreign target turns perception into a way to look at another application."""
    driver = _driver()
    observed = UiaEffector(driver, WINDOW).perceive(f"{SCHEME}Calculator/Field")
    assert observed.data["window"] == WINDOW
    assert [r["args"][0] for r in driver.requests] == [WINDOW]


def test_an_ambiguous_control_label_is_refused_rather_than_guessed():
    window = _window(elements=[{"name": "Save as"}, {"name": "Save all"}])
    with pytest.raises(RefusedActuation, match="ambiguous"):
        UiaEffector(_driver(window), WINDOW).preview(f"{SCHEME}{WINDOW}/Sav",
                                                     UiaCommand("invoke", expect={}))


def test_a_control_that_does_not_resolve_is_refused():
    with pytest.raises(RefusedActuation, match="does not resolve"):
        UiaEffector(_driver(), WINDOW).preview(f"{SCHEME}{WINDOW}/Print",
                                               UiaCommand("set_value", text="x"))


def test_a_target_that_is_not_a_control_address_is_refused():
    effector = UiaEffector(_driver(), WINDOW)
    for bad in (WINDOW, f"{SCHEME}{WINDOW}", f"{SCHEME}/Field", "/etc/passwd"):
        with pytest.raises(RefusedActuation, match="uia target"):
            effector.preview(bad, UiaCommand("set_value", text="x"))


def test_an_intent_this_rung_does_not_serve_is_refused():
    with pytest.raises(RefusedActuation, match="not one this rung serves"):
        UiaEffector(_driver(), WINDOW).preview(FIELD, UiaCommand("drag", text="x"))


def test_an_invoke_without_a_post_condition_is_refused_before_anything_is_touched():
    """An invoke cannot be undone, so it is only authorizable if it is verifiable, and
    only the caller knows what the click should produce."""
    driver = _driver()
    with pytest.raises(RefusedActuation, match="post-condition"):
        UiaEffector(driver, WINDOW).preview(SAVE, UiaCommand("invoke"))
    assert not [r for r in driver.requests if r["verb"] in ("invoke", "setvalue")]


def test_a_post_condition_this_rung_cannot_check_is_refused():
    effector = UiaEffector(_driver(), WINDOW)
    for expect in ({"kind": "sounds_right", "element": "Saved"},
                   {"kind": "appears"},
                   {"kind": "value_is", "element": "Field"}):
        with pytest.raises(RefusedActuation):
            effector.preview(SAVE, UiaCommand("invoke", expect=expect))


def test_an_act_without_a_gate_allow_touches_nothing():
    driver = _driver()
    effector = UiaEffector(driver, WINDOW)
    command = UiaCommand("set_value", text="after")
    plan = effector.preview(FIELD, command)
    with pytest.raises(RefusedActuation, match="no gate allow"):
        effector.act(plan, allow_receipt=None, command=command)
    assert not [r for r in driver.requests if r["verb"] == "setvalue"]
    assert driver.windows[WINDOW].values["Field"] == "before"


def test_an_allow_for_another_control_does_not_authorize_this_one():
    """The receipt is bound to one plan. A grant naming the action kind is not a grant
    for every control the window happens to carry."""
    driver = _driver()
    effector = UiaEffector(driver, WINDOW)
    command = UiaCommand("set_value", text="after")
    plan = effector.preview(FIELD, command)
    elsewhere = AccountableSurface().propose(
        action_kind="uia.set_value", target=SAVE, authorization=_grant(["uia.set_value"]))
    assert elsewhere.decision == "allow"
    with pytest.raises(RefusedActuation, match="does not match the plan"):
        effector.act(plan, elsewhere, command)
    assert driver.windows[WINDOW].values["Field"] == "before"


def test_a_command_that_is_not_the_previewed_one_does_not_act():
    driver = _driver()
    effector = UiaEffector(driver, WINDOW)
    plan = effector.preview(FIELD, UiaCommand("set_value", text="after"))
    allow = AccountableSurface().propose(action_kind="uia.set_value", target=FIELD,
                                         authorization=_grant(["uia.set_value"]))
    with pytest.raises(RefusedActuation, match="previewed"):
        effector.act(plan, allow, UiaCommand("set_value", text="something else"))
    assert driver.windows[WINDOW].values["Field"] == "before"


def test_the_effector_selftest_is_falsifiable():
    assert UiaEffector(_driver(), WINDOW).selftest() is True

    class ObedientEffector(UiaEffector):
        """Acts on anything handed to it, which is the contract violation the selftest
        exists to catch."""

        def act(self, plan, allow_receipt, command):
            _, element = self._parse(plan.target)
            self._driver.run("setvalue", [self._window, element, command.text])
            return self.perceive(plan.target)

    assert ObedientEffector(_driver(), WINDOW).selftest() is False


# --- through the surface: gate, act, re-read, verify -------------------------


def test_a_set_value_acts_and_verifies_by_re_reading_the_control():
    driver = _driver()
    surface = AccountableSurface()
    outcome = surface.actuate(UiaEffector(driver, WINDOW), target=FIELD,
                              content=UiaCommand("set_value", text="after"),
                              authorization=_grant(["uia.set_value"]))
    assert outcome.acted is True
    assert outcome.verified is True
    assert outcome.rolled_back is False
    assert driver.windows[WINDOW].values["Field"] == "after"
    entry = [e for e in surface.journal if e.kind == "actuation"][-1]
    assert entry.detail["effector_bound"] == f"uia:windows={WINDOW}"
    assert entry.detail["verdict"] == "pass"


def test_the_verify_re_reads_the_window_rather_than_believing_the_act():
    """The instrument answers `ok` for a write it dispatched, which says nothing about
    what the application did with it. Every verify has to be a fresh read."""
    driver = _driver()
    _act(UiaEffector(driver, WINDOW), FIELD, UiaCommand("set_value", text="after"),
         ["uia.set_value"])
    verbs = [r["verb"] for r in driver.requests]
    assert "setvalue" in verbs
    assert "value" in verbs[verbs.index("setvalue") + 1:]


def test_an_invoke_is_irreversible_so_the_surface_escalates_to_needs_human():
    """A click cannot be unclicked. A bare grant is not enough for that, and the
    escalation is UNVERIFIABLE rather than a refusal rounded down."""
    driver = _driver()
    outcome = _act(UiaEffector(driver, WINDOW), SAVE, UiaCommand("invoke", expect=SAVED),
                   ["uia.invoke"])
    assert outcome.acted is False
    assert outcome.decision == "needs-human"
    assert outcome.verdict == "irreversible-needs-human"
    assert not [r for r in driver.requests if r["verb"] == "invoke"]


def test_an_invoke_the_operator_pre_authorized_acts_and_verifies_its_post_condition():
    window = _window(effects={"Save": {"add": [{"name": "Saved", "type": "Text"}]}})
    outcome = _act(UiaEffector(_driver(window), WINDOW), SAVE,
                   UiaCommand("invoke", expect=SAVED), ["uia.invoke"],
                   allow_irreversible=True)
    assert outcome.acted is True
    assert outcome.verified is True
    assert outcome.rolled_back is False


@pytest.mark.parametrize("effect,expect", [
    ({"remove": ["Field"]}, {"kind": "disappears", "element": "Field"}),
    ({"set": {"Field": "saved"}}, {"kind": "value_is", "element": "Field", "text": "saved"}),
])
def test_the_other_post_conditions_are_checked_against_the_window(effect, expect):
    window = _window(effects={"Save": effect})
    outcome = _act(UiaEffector(_driver(window), WINDOW), SAVE,
                   UiaCommand("invoke", expect=expect), ["uia.invoke"],
                   allow_irreversible=True)
    assert outcome.acted is True
    assert outcome.verified is True


def test_a_control_the_window_will_not_invoke_comes_back_as_a_refusal_not_a_crash():
    window = _window(no_invoke={"Save"})
    outcome = _act(UiaEffector(_driver(window), WINDOW), SAVE,
                   UiaCommand("invoke", expect=SAVED), ["uia.invoke"],
                   allow_irreversible=True)
    assert outcome.acted is False
    assert outcome.verdict == "refused-by-effector"
    assert "InvokePattern" in " ".join(outcome.reasons)


def test_a_grant_for_one_intent_does_not_carry_the_other():
    """Two action kinds rather than one, so the reversible intent can be granted on its
    own without carrying the click that cannot be undone."""
    driver = _driver()
    outcome = _act(UiaEffector(driver, WINDOW), SAVE, UiaCommand("invoke", expect=SAVED),
                   ["uia.set_value"], allow_irreversible=True)
    assert outcome.acted is False
    assert outcome.decision != "allow"
    assert not [r for r in driver.requests if r["verb"] == "invoke"]


class _DroppingDriver(FakeUiaDriver):
    """Reports a successful write and stores nothing the first time, the way an
    application that is busy, disabled, or validating silently would."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dropped = False

    def _setvalue(self, title, window, rest):
        if not self.dropped:
            self.dropped = True
            return {"ok": True, "name": rest[0], "matched": "name-exact"}
        return super()._setvalue(title, window, rest)


def test_a_set_value_the_window_dropped_is_rolled_back_to_the_prior_value():
    driver = _DroppingDriver({WINDOW: _window()})
    outcome = _act(UiaEffector(driver, WINDOW), FIELD, UiaCommand("set_value", text="after"),
                   ["uia.set_value"])
    assert outcome.acted is True
    assert outcome.verified is False
    assert outcome.rolled_back is True
    assert driver.windows[WINDOW].values["Field"] == "before"
    restored = [r for r in driver.requests if r["verb"] == "setvalue"][-1]
    assert restored["args"][-1] == "before"


def test_uia_is_refused_by_name_over_mcp(tmp_path):
    """This rung acts on a window belonging to whoever is at the machine. Reaching it
    from off the machine is a separate decision, and it has not been made."""
    spec = tmp_path / "effectors.json"
    spec.write_text(json.dumps({"effectors": [{"action_kind": "uia.invoke", "type": "uia",
                                               "window": WINDOW}]}), encoding="utf-8")
    registry = load_effectors(str(spec))
    assert registry.action_kinds() == []
    assert registry.get("uia.invoke") is None
    assert any("deliberately not exposed" in reason for reason in registry.refusals())
