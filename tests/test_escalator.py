"""Rung ordering: the cheapest instrument first, and a record of why it fell.

The rungs themselves are held in `test_uia_structure.py` and `test_uia_effector.py`.
What is under pressure here is the seam between them. A ladder that falls to a more
expensive instrument has to come back with a worse answer or no answer at all, and
the tempting bug is the opposite: paying for rung 3 and treating the receipt as
though rung 0 had answered.
"""

from __future__ import annotations

import pytest
from coherence_membrane.observation import Status
from coherence_membrane.pngencode import encode_png

from accountable_surface.escalator import (
    Ascent,
    Escalator,
    PixelProbe,
    Question,
    StructureProbe,
    structure_ladder,
)
from accountable_surface.uia import FakeUiaDriver, FakeWindow, UiaStructureOrgan

WINDOW = "Notepad"
ASK = Question("present", "Save")


def _window(names=("Field", "Save")):
    return FakeWindow(elements=[{"name": n} for n in names], values={})


def _driver(window=None, **kwargs):
    return FakeUiaDriver({WINDOW: window or _window()}, **kwargs)


class _Camera:
    """A capture that counts how often the ladder actually paid for it."""

    def __init__(self, shade=200, w=12, h=8):
        self.calls = 0
        self._png = encode_png(w, h, bytes([shade, shade, shade] * w * h), channels=3)

    def __call__(self):
        self.calls += 1
        return self._png


def _ladder(driver, camera, max_elements=400):
    return structure_ladder(UiaStructureOrgan(driver, max_elements), WINDOW, camera)


# --- rung 0 answers, and the ladder stops there -----------------------------


def test_a_label_that_resolves_is_answered_at_the_cheapest_rung():
    camera = _Camera()
    ascent = _ladder(_driver(), camera).resolve(ASK)
    assert ascent.answer is True
    assert ascent.status is Status.PASS
    assert ascent.rederivable == "by name and role"
    assert len(ascent.attempts) == 1
    assert camera.calls == 0  # rung 3 was never paid for


def test_a_whole_tree_settles_absence_without_climbing():
    """A complete tree that does not carry the label HAS answered the question. The
    negative is a result, not a failure to find something."""
    camera = _Camera()
    ascent = _ladder(_driver(_window(names=("Field",))), camera).resolve(ASK)
    assert ascent.answer is False
    assert ascent.status is Status.PASS
    assert camera.calls == 0
    assert "the tree was whole" in ascent.attempts[0].reason


# --- what makes it fall, and what the fall costs ----------------------------


def test_a_clipped_tree_falls_rather_than_reading_a_missing_control_as_gone():
    camera = _Camera()
    driver = _driver(_window(names=("Field", "Other")), truncate_at=1)
    ascent = _ladder(driver, camera).resolve(ASK)
    assert ascent.answer is None
    assert ascent.status is Status.NEEDS_HUMAN
    assert ascent.attempts[0].outcome == "fell"
    assert "absence is not established" in ascent.attempts[0].reason
    assert camera.calls == 1


def test_a_tree_with_nothing_named_falls_and_says_which_way_it_failed():
    """The clipped tree announces itself. This one does not: the walk finished, nothing
    was cut, and the listing is the same shape a window with no such control returns.
    Reading it as a settled negative is the quiet false success, so the fall carries
    which of the two ways the listing failed rather than one reason for both."""
    camera = _Camera()
    ascent = _ladder(_driver(FakeWindow(elements=[], values={})), camera).resolve(ASK)
    assert ascent.answer is None
    assert ascent.status is Status.NEEDS_HUMAN
    fell = ascent.attempts[0]
    assert fell.outcome == "fell"
    assert "nothing it saw carried a name" in fell.reason
    assert "absence is not established" in fell.reason
    assert "clipped" not in fell.reason
    assert camera.calls == 1  # the ladder paid for rung 3 rather than guessing


def test_a_label_naming_two_controls_falls_and_names_them():
    driver = _driver(_window(names=("Save draft", "Save and close")))
    ascent = _ladder(driver, _Camera()).resolve(ASK)
    assert ascent.answer is None
    reason = ascent.attempts[0].reason
    assert "Save draft" in reason and "Save and close" in reason


def test_a_window_that_does_not_read_falls_with_the_instrument_reason():
    ascent = _ladder(FakeUiaDriver({}), _Camera()).resolve(ASK)
    assert ascent.answer is None
    assert ascent.attempts[0].outcome == "fell"
    assert WINDOW in ascent.attempts[0].reason


# --- the fall never buys an answer ------------------------------------------


def test_paying_for_pixels_does_not_turn_into_a_verdict():
    """The bug this ladder exists to prevent: a rung that cannot read control names
    returning a perception, and the ascent reporting it as though the question were
    settled."""
    driver = _driver(truncate_at=1)
    ascent = _ladder(driver, _Camera()).resolve(ASK)
    pixels = ascent.attempts[-1]
    assert pixels.rung.index == 3
    assert pixels.outcome == "fell"
    assert pixels.observation is not None  # a real perception came back
    assert ascent.answer is None  # and it still answered nothing
    assert ascent.status is Status.NEEDS_HUMAN
    assert ascent.rederivable == "none"


def test_the_ascent_hands_the_person_the_deepest_perception_it_bought():
    driver = _driver(truncate_at=1)
    ascent = _ladder(driver, _Camera()).resolve(ASK)
    witness = ascent.witness
    assert witness is not None
    assert witness.organ == "pixel-sight"
    assert witness.status is Status.NEEDS_HUMAN
    assert len(witness.data["phash"]) == 16
    assert witness.data["phash"] in ascent.attempts[-1].reason


def test_a_capture_that_fails_falls_back_to_the_structural_perception():
    def broken():
        raise OSError("no display")

    driver = _driver(truncate_at=1)
    ascent = Escalator([StructureProbe(UiaStructureOrgan(driver), WINDOW),
                        PixelProbe(broken)]).resolve(ASK)
    assert ascent.answer is None
    assert ascent.attempts[-1].observation is None
    assert "no display" in ascent.attempts[-1].reason
    assert ascent.witness is not None and ascent.witness.organ == "uia-structure"


def test_the_trace_records_every_rung_that_was_paid_for():
    driver = _driver(truncate_at=1)
    trace = _ladder(driver, _Camera()).resolve(ASK).trace().splitlines()
    assert len(trace) == 2
    assert trace[0].startswith("rung 0 structure (low cost): fell")
    assert trace[1].startswith("rung 3 pixels (high cost): fell")


# --- what the escalator refuses ---------------------------------------------


def test_resolving_never_sends_a_verb_that_changes_anything():
    """An escalator that pressed a control to find out what it did would be an
    actuation no grant authorized. Only reads leave here."""
    driver = _driver(truncate_at=1)
    _ladder(driver, _Camera()).resolve(ASK)
    assert {r["verb"] for r in driver.requests} == {"tree"}


def test_a_question_no_rung_carries_is_refused():
    with pytest.raises(ValueError, match="not a question this ladder carries"):
        _ladder(_driver(), _Camera()).resolve(Question("press", "Save"))


def test_two_probes_claiming_one_rung_have_no_order():
    with pytest.raises(ValueError, match="same rung"):
        Escalator([PixelProbe(_Camera()), PixelProbe(_Camera())])


def test_a_ladder_with_no_rungs_is_refused():
    with pytest.raises(ValueError, match="cannot answer anything"):
        Escalator([])


def test_the_rungs_are_climbed_in_cost_order_however_they_were_handed_in():
    camera = _Camera()
    out_of_order = Escalator([PixelProbe(camera),
                              StructureProbe(UiaStructureOrgan(_driver()), WINDOW)])
    ascent = out_of_order.resolve(ASK)
    assert [a.rung.index for a in ascent.attempts] == [0]
    assert camera.calls == 0


# --- the selftest is falsifiable --------------------------------------------


def test_the_escalator_selftest_is_falsifiable():
    assert _ladder(_driver(), _Camera()).selftest() is True

    class RoundingEscalator(Escalator):
        """Reports a pass for a ladder where every rung declined."""

        def resolve(self, question):
            attempts = tuple(p.attempt(question) for p in self._probes)
            return Ascent(question, attempts, True, Status.PASS, "by name and role")

    assert RoundingEscalator([StructureProbe(UiaStructureOrgan(_driver()), WINDOW)]).selftest() is False
