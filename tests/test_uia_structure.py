"""Rung 0: what a structural read of a window settles, and what it does not.

Nothing here needs Windows, a window, or an application. `FakeUiaDriver` answers in
the shapes `uia.ps1` answers in, so the read, its limits, and the transport's verb
refusals are all testable at a desk. The rung above is in `test_uia_effector.py`.
"""

from __future__ import annotations

import json
from dataclasses import replace

from coherence_membrane.observation import Status

from accountable_surface.uia import (
    FakeUiaDriver,
    FakeWindow,
    UiaStructureOrgan,
    match_element,
)
from accountable_surface.uia_transport import PowerShellUiaDriver

WINDOW = "Notepad"


def _window(**kwargs):
    base = {
        "elements": [
            {"name": "Field", "type": "Edit", "automationId": "field-1"},
            {"name": "Save", "type": "Button", "automationId": "save-1"},
        ],
        "values": {"Field": "before"},
    }
    base.update(kwargs)
    return FakeWindow(**base)


def _driver(window=None, **kwargs):
    return FakeUiaDriver({WINDOW: window or _window()}, **kwargs)


# --- what a structural read settles ------------------------------------------


def test_a_tree_read_witnesses_names_roles_and_ids_and_nothing_else():
    """What is witnessed has to be what another party can re-derive from the same
    window, so anything the fixture carries beyond the three structural facts must
    not reach the digest."""
    window = _window(elements=[{"name": "Field", "type": "Edit", "automationId": "field-1",
                                "runtimeId": "42-7", "boundingRect": [0, 0, 10, 10]}])
    observed = UiaStructureOrgan(_driver(window)).observe(WINDOW)
    assert observed.data["elements"] == [{"name": "Field", "type": "Edit",
                                          "automationId": "field-1"}]
    assert "runtimeId" not in json.dumps(observed.data["elements"])
    assert observed.status is Status.PASS
    assert observed.provenance.command == f"uia.ps1 tree {WINDOW} 400"


def test_a_truncated_tree_is_not_a_settled_read():
    """A clipped tree is a partial view: a control that exists can read as absent, so
    the read is UNVERIFIED and says why in the summary an operator sees."""
    observed = UiaStructureOrgan(_driver(truncate_at=1)).observe(WINDOW)
    assert observed.status is Status.UNVERIFIED
    assert observed.data["truncated"] is True
    assert observed.data["descendants"] == 2
    assert observed.data["settles_absence"] is False
    assert "TRUNCATED" in observed.summary


def test_a_tree_that_came_back_with_nothing_named_is_not_a_settled_read():
    """The quiet failure. Nothing was clipped and the walk finished, so the answer is
    shaped exactly like a window holding no such control. Nothing in it separates a
    window with no named controls from one that would not open its tree, so the read
    settles nothing and says so where an operator reads it."""
    observed = UiaStructureOrgan(_driver(FakeWindow())).observe(WINDOW)
    assert observed.status is Status.UNVERIFIED
    assert observed.data["opaque"] is True
    assert observed.data["truncated"] is False
    assert observed.data["settles_absence"] is False
    assert "OPAQUE" in observed.summary


class _ClaimingDriver(FakeUiaDriver):
    """A driver whose tree answer states a settlesAbsence of its own choosing."""

    def __init__(self, windows, claim, **kwargs):
        super().__init__(windows, **kwargs)
        self._claim = claim

    def run(self, verb, args):
        answer = super().run(verb, args)
        if verb == "tree" and answer.get("ok"):
            answer["settlesAbsence"] = self._claim
        return answer


def test_the_instruments_claim_can_veto_a_settled_read_and_cannot_grant_one():
    """`uia.ps1` states settlesAbsence too. Reading it verbatim would let the thing
    being measured decide whether the measurement counts, so the organ derives the bit
    from the facts and the claim only subtracts. A driver saying a whole tree settles
    nothing is believed. A driver saying an empty one does is not."""
    vetoed = UiaStructureOrgan(
        _ClaimingDriver({WINDOW: _window()}, False)).observe(WINDOW)
    assert vetoed.status is Status.UNVERIFIED
    assert vetoed.data["settles_absence"] is False

    flattered = UiaStructureOrgan(
        _ClaimingDriver({WINDOW: FakeWindow()}, True)).observe(WINDOW)
    assert flattered.status is Status.UNVERIFIED
    assert flattered.data["settles_absence"] is False
    assert flattered.data["opaque"] is True


def test_a_window_that_does_not_resolve_is_unverified_and_carries_the_reason():
    observed = UiaStructureOrgan(_driver()).observe("Calculator")
    assert observed.status is Status.UNVERIFIED
    assert observed.data["ok"] is False
    assert "no window matched" in observed.summary


def test_the_same_window_reads_to_the_same_digest_and_a_changed_one_does_not():
    """Re-derivability is the whole claim of this rung, so two reads of an unchanged
    window have to agree byte for byte."""
    window = _window()
    organ = UiaStructureOrgan(FakeUiaDriver({WINDOW: window}))
    first, second = organ.observe(WINDOW), organ.observe(WINDOW)
    assert first.provenance.digest == second.provenance.digest
    window.elements.append({"name": "Cancel", "type": "Button", "automationId": "cancel-1"})
    assert organ.observe(WINDOW).provenance.digest != first.provenance.digest


def test_the_structure_organ_selftest_is_falsifiable():
    """The selftest is only worth running if a broken organ fails it."""
    assert UiaStructureOrgan(_driver()).selftest() is True

    class CredulousOrgan(UiaStructureOrgan):
        """Calls a partial tree a settled read, which is the mistake the status exists
        to prevent."""

        def observe(self, window):
            return replace(super().observe(window), status=Status.PASS)

    assert CredulousOrgan(_driver()).selftest() is False


def test_the_resolution_ladder_matches_the_instruments_own_order():
    """A plan has to resolve a control offline the same way the live window would, so
    the ladder is mirrored rather than reinvented: exact name, exact AutomationId,
    then a unique substring."""
    elements = [{"name": "Save as", "automationId": "save-1"},
                {"name": "Save", "automationId": "save-as-1"}]
    assert match_element(elements, "Save")["how"] == "name-exact"
    assert match_element(elements, "Save")["index"] == 1
    assert match_element(elements, "save-1")["how"] == "automationid-exact"
    assert match_element(elements, "as")["how"] == "name-substring-unique"
    assert match_element(elements, "sav")["status"] == "ambiguous"
    assert match_element(elements, "Print")["status"] == "none"
    assert match_element(elements, "")["status"] == "invalid"


def test_a_label_two_controls_carry_is_refused_on_every_rung():
    """`Select-Candidate` in `uia.ps1` refuses a duplicate on the exact rungs, not only
    on the substring one. Taking the first hit here would resolve offline what the live
    window refuses, and a plan that passes rung 0 and is turned away at rung 1 is worse
    than either answer alone."""
    twins = [{"name": "Save", "automationId": "a"}, {"name": "Save", "automationId": "b"}]
    chosen = match_element(twins, "Save")
    assert chosen["status"] == "ambiguous"
    assert chosen["how"] == "name-exact"
    assert chosen["candidates"] == ["Save", "Save"]

    shared_id = [{"name": "Left", "automationId": "same"},
                 {"name": "Right", "automationId": "same"}]
    by_id = match_element(shared_id, "same")
    assert by_id["status"] == "ambiguous"
    assert by_id["how"] == "automationid-exact"
    assert by_id["candidates"] == ["Left", "Right"]   # what separates them, not a count


def test_resolution_ignores_case_the_way_the_instrument_does():
    """PowerShell compares strings with `-eq`, which folds case. A ladder that did not
    would refuse a control the live window resolves, so the mismatch is worth holding."""
    elements = [{"name": "Save", "automationId": "Save-1"}]
    assert match_element(elements, "SAVE")["how"] == "name-exact"
    assert match_element(elements, "save-1")["index"] == 0


# --- the transport's own refusals --------------------------------------------


def test_the_blind_keystroke_verbs_are_refused_before_anything_is_spawned(tmp_path):
    """`uia.ps1` also types into whatever window is in front. That names no control and
    nothing about it can be verified by re-reading a tree, so the driver refuses it."""
    driver = PowerShellUiaDriver(tmp_path / "uia.ps1")
    for verb in ("input", "type"):
        answer = driver.run(verb, ["hello"])
        assert answer["ok"] is False
        assert "refused" in answer["error"]


def test_a_verb_this_driver_does_not_run_is_refused(tmp_path):
    answer = PowerShellUiaDriver(tmp_path / "uia.ps1").run("screenshot", [])
    assert answer["ok"] is False
    assert "not one this driver runs" in answer["error"]
