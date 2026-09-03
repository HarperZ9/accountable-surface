"""The README's diagrams are generated from a spec, so they can go stale the way any
other derived file goes stale: somebody renames a stage, nobody re-renders, and the
picture describes a version of accountable-surface that no longer exists. The gate
re-renders from the spec and compares bytes. This runs the gate under pytest and asserts
on its receipt, so a drifted drawing fails the suite instead of quietly shipping."""

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GATE = _REPO / "tools" / "check_repo_art.py"
_SPEC = _REPO / "docs" / "art" / "accountable-surface.art.json"

GATES = (
    "spec.present",
    "art.matches_spec",
    "art.render_is_deterministic",
    "art.identity_per_repository",
    "art.seed_is_recorded",
    "art.no_local_paths_or_em_dashes",
    "art.spec_words_reach_the_drawing",
    "art.note_survives_the_wrapper",
    "art.return_edge_stays_on_its_row",
    "art.every_illustration_is_shown",
    "art.tagline_stays_inside_its_rule",
    "art.outcome_fits_its_box",
    "art.card_draws_shapes_not_digits",
    "art.card_text_fits_its_column",
    "art.card_widths_bound_every_face",
    "art.card_draws_measured_characters",
    "art.card_carries_one_mark",
    "art.card_alt_reaches_the_readme",
    "art.the_gate_can_fail",
)

DRAWINGS = (
    "docs/art/accountable-surface-header.svg",
    "docs/art/actuation-lane.svg",
    "docs/art/journal-chain-lane.svg",
    "docs/art/verdict-composition.svg",
)


def _receipt() -> dict:
    out = subprocess.run([sys.executable, str(_GATE), "--json"],
                         cwd=_REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    return json.loads(out.stdout)


def test_every_gate_passes_and_the_receipt_names_what_it_ran():
    receipt = _receipt()
    assert receipt["schema"] == "accountable-surface.repo-art/v1"
    assert [c["name"] for c in receipt["checks"]] == list(GATES)
    assert all(c["passed"] for c in receipt["checks"]), \
        [c for c in receipt["checks"] if not c["passed"]]


def test_both_diagrams_and_the_card_are_accounted_for():
    receipt = _receipt()
    assert receipt["specs"] == ["docs/art/accountable-surface.art.json"]
    drawn = {out["file"]: out for out in receipt["outputs"]}
    assert set(drawn) == set(DRAWINGS)
    for path, out in drawn.items():
        assert len(out["sha256"]) == 64, path
        assert out["bytes"] > 0, path


def test_a_gate_that_cannot_fail_is_not_a_gate(tmp_path, monkeypatch):
    """Point the outcome-box check at a note too wide for its box and it has to
    complain. Without this, a green suite proves only that the gate ran."""
    sys.path.insert(0, str(_REPO / "tools"))
    import check_repo_art as gate
    spec = json.loads(_SPEC.read_text("utf-8"))
    spec["flows"][0]["outcomes"][0]["note"] = "x" * 80
    (tmp_path / "accountable-surface.art.json").write_text(json.dumps(spec),
                                                           encoding="utf-8")
    monkeypatch.setattr(gate, "ART", tmp_path)
    assert len(gate.check_outcome_fits_its_box([])) == 1


# verdict-composition.svg draws each verdict the surface produces beside what it
# contributes to the composed certificate, and journal-chain-lane.svg draws how an
# edited or moved entry gives itself away. Those are claims about certify.py and
# journal_chain.py, so nothing under tools/ can settle them. Every row and stage
# below is driven against running code.

from types import SimpleNamespace  # noqa: E402

from coherence_membrane.certificate import Verdict  # noqa: E402

from accountable_surface.certify import action_certificate  # noqa: E402
from accountable_surface.effector import FilesystemEffector  # noqa: E402
from accountable_surface.journal_chain import read_journal  # noqa: E402
from accountable_surface.surface import AccountableSurface  # noqa: E402

VERIFIED_THROUGHOUT = {"decision": "allow", "verdict": "pass", "acted": True,
                       "before_digest": "sha256:before", "after_digest": "sha256:after"}

NOT_ACTED = {"verdict": "not-acted", "acted": False, "after_digest": None}


def _grounding(confidence: str):
    return SimpleNamespace(confidence=confidence, digest="sha256:" + "a" * 64)


# One call per drawn row, each holding every other input at verified so the row's
# own contribution is the only thing that can move the composed verdict.
ROW_CALLS = {
    "gate allow": {},
    "gate deny": dict(NOT_ACTED, decision="deny"),
    "gate needs-human": dict(NOT_ACTED, decision="needs-human"),
    "effect pass": {},
    "effect failed": {"verdict": "failed"},
    "effector refusal": dict(NOT_ACTED, verdict="refused-by-effector"),
    "grounding grounded": {"grounding": _grounding("grounded")},
    "grounding weak": {"grounding": _grounding("weak")},
    "grounding ungrounded": {"grounding": _grounding("ungrounded")},
    "anything else": {"grounding": _grounding("fairly-well-supported")},
}


def _card() -> dict:
    spec = json.loads(_SPEC.read_text("utf-8"))
    return next(c for c in spec["cards"] if c["file"] == "verdict-composition.svg")


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1", "receipt_id": "rcpt-repo-art",
        "kind": "authorization-grant", "intent": "write the report file",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "repo-art-agent"},
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00", "revoked": False,
    }


class _FaultyEffector(FilesystemEffector):
    """Writes bytes the plan never authorized, so verification has something to catch."""

    def _write(self, path, content):
        path.write_bytes(b"CORRUPTED-OUTPUT")


def test_the_card_draws_every_verdict_the_composition_knows_about():
    """A row drawn for an input the code does not take, or an input taken and not
    drawn, makes the table a description of a different tool."""
    assert [f["key"] for f in _card()["fields"]] == list(ROW_CALLS)


def test_each_row_composes_to_the_verdict_it_is_drawn_with():
    """The whole claim of the table. Run the real composition once per row with
    every other input held at verified, and read the result back."""
    for field in _card()["fields"]:
        composed = action_certificate(**dict(VERIFIED_THROUGHOUT,
                                             **ROW_CALLS[field["key"]]))
        assert composed.verdict.name == field["value"], field["key"]


def test_the_three_drawn_values_are_the_three_verdicts_that_exist():
    """The `becomes` column is not free text. It names the certificate verdicts,
    so a fourth one added to the type would leave the table incomplete."""
    drawn = {f["value"] for f in _card()["fields"]}
    assert drawn == {v.name for v in Verdict}


def test_the_marked_row_is_the_one_that_degrades_instead_of_raising():
    """The accent sits on totality: an unrecognized verdict string is treated as
    unverifiable and never raises. No other row is marked."""
    marked = [f["key"] for f in _card()["fields"] if f.get("tone", "none") != "none"]
    assert marked == ["anything else"]
    for junk in ("", "ALLOW", "allow ", "probably-fine"):
        composed = action_certificate(**dict(VERIFIED_THROUGHOUT, decision=junk))
        assert composed.verdict is Verdict.UNVERIFIABLE, junk


def test_one_refuted_input_absorbs_wherever_it_sits():
    """The card footnote says refuted absorbs. Put the denial in the gate, then in
    the effect, then in the grounding, and the composed verdict does not move."""
    for override in ({"decision": "deny"}, {"verdict": "failed"},
                     {"grounding": _grounding("ungrounded")}):
        composed = action_certificate(**dict(VERIFIED_THROUGHOUT, **override))
        assert composed.verdict is Verdict.REFUTED, override


def test_an_allowed_write_lands_and_the_surface_confirms_it_by_re_reading(tmp_path):
    """Stages perceive through verify in actuation-lane.svg. The file is written,
    and `verified` comes from reading the target back, not from the write call."""
    target = str(tmp_path / "report.txt")
    content = b"written natively, verified by re-perceiving"
    out = AccountableSurface().actuate(
        FilesystemEffector(tmp_path), target=target, content=content,
        authorization=_grant(["fs.write"]))
    assert (out.acted, out.decision, out.verified) == (True, "allow", True)
    assert Path(target).read_bytes() == content
    assert out.rolled_back is False


def test_without_a_grant_the_gate_stops_the_write_before_it_happens(tmp_path):
    """The `not acted` outcome. The gate stage sits ahead of the act stage, so a
    denial leaves the target exactly as the perceive stage found it."""
    target = str(tmp_path / "report.txt")
    out = AccountableSurface().actuate(
        FilesystemEffector(tmp_path), target=target, content=b"x", authorization={})
    assert (out.acted, out.decision, out.verified) == (False, "deny", False)
    assert not Path(target).exists()


def test_a_write_that_lands_wrong_is_undone_and_the_prior_bytes_come_back(tmp_path):
    """The return edge: roll back, then read the target a second time. A faulty
    effector writes bytes the plan never authorized, so verification fails."""
    target = tmp_path / "report.txt"
    target.write_bytes(b"the previous contents")
    out = AccountableSurface().actuate(
        _FaultyEffector(tmp_path), target=str(target), content=b"the new contents",
        authorization=_grant(["fs.write"]))
    assert (out.acted, out.verified, out.rolled_back) == (True, False, True)
    assert target.read_bytes() == b"the previous contents"


def test_the_effector_refuses_a_write_that_carries_no_allow():
    """The act stage is drawn as conditional on the gate. The effector ships its
    own falsifiable probe for exactly that, and it has to come back true."""
    assert FilesystemEffector(".").selftest() is True


def _journalled(tmp_path) -> Path:
    """Two real actuations against a persisted journal: one allowed, one denied."""
    path = tmp_path / "journal.jsonl"
    surface = AccountableSurface(journal_path=path)
    effector = FilesystemEffector(tmp_path)
    surface.actuate(effector, target=str(tmp_path / "a.txt"), content=b"one",
                    authorization=_grant(["fs.write"]))
    surface.actuate(effector, target=str(tmp_path / "b.txt"), content=b"two",
                    authorization={})
    assert path.exists()
    return path


def test_an_untouched_journal_rechains_from_end_to_end(tmp_path):
    """The match outcome. Every entry the surface wrote links to the one before it,
    and reloading re-derives the whole chain without a break."""
    loaded = read_journal(_journalled(tmp_path))
    assert loaded["tamper_count"] == 0
    assert loaded["replay_errors"] == 0
    assert len(loaded["records"]) >= 2


def test_an_edit_a_delete_and_a_reorder_each_break_the_chain(tmp_path):
    """The three failure stages, driven one at a time. Each rewrite still parses as
    JSON, which is the point: parsing was never what caught them."""
    path = _journalled(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2

    edited = [line.replace('"acted":true', '"acted":false') for line in lines]
    assert edited != lines
    for rewrite in (edited, lines[1:], list(reversed(lines))):
        probe = tmp_path / "probe.jsonl"
        probe.write_text("\n".join(rewrite) + "\n", encoding="utf-8")
        loaded = read_journal(probe)
        assert loaded["tamper_count"] >= 1, rewrite[0][:60]
        assert loaded["replay_errors"] == 0


def test_a_line_that_will_not_parse_is_counted_apart_from_a_break(tmp_path):
    """The unverifiable outcome. A corrupt line is not evidence of tampering, and
    the drawing says the two counts never merge."""
    path = _journalled(tmp_path)
    probe = tmp_path / "probe.jsonl"
    probe.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    loaded = read_journal(probe)
    assert loaded["replay_errors"] == 1
    assert loaded["tamper_count"] == 0


def test_the_three_outcomes_are_the_three_verdicts_the_offline_verifier_prints(tmp_path):
    """The flow says a stranger holding only the file can check it. Run the vendored
    verifier as its own process, with nothing from this package importable."""
    path = _journalled(tmp_path)
    good = path.read_text(encoding="utf-8")
    cases = {
        "MATCH": (good, 0),
        "DRIFT": (good.replace('"acted":true', '"acted":false', 1), 1),
        "UNVERIFIABLE": (good + '{"summary": "no kind here"}\n', 2),
    }
    drawn = {o["label"] for o in json.loads(_SPEC.read_text("utf-8"))
             ["flows"][1]["outcomes"]}
    assert drawn == set(cases)
    for label, (text, code) in cases.items():
        probe = tmp_path / "probe.jsonl"
        probe.write_text(text, encoding="utf-8")
        out = subprocess.run([sys.executable, str(_REPO / "verify_journal.py"),
                              str(probe)], capture_output=True, text=True)
        assert out.returncode == code, (label, out.stdout, out.stderr)
        assert label in out.stdout, (label, out.stdout)
