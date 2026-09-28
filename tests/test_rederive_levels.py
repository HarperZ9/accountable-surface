"""Re-derivation of an actuation session from its receipts and evidence, offline.

    L0 chain     every seal and link re-derives (actuation_receipt.verify_chain)
    L1 evidence  every referenced blob exists and re-hashes to its name
    L2 policy    policy.decide re-run on the stored inputs gives the recorded outcome
    L3 verdict   the predicate re-run on the stored after evidence gives the verdict

The resealing tests matter most: a writer who knows the chain rule can rewrite
a receipt and reseal the whole file, and L0 then reads MATCH. Only L2 and L3,
which recompute the decision and the verdict from evidence, catch it.
"""

from __future__ import annotations

import json

import pytest
from actuation_site import Site
from actuation_world import CARD, PASSWORD, SpyDriver, World

from accountable_surface import rederive
from accountable_surface.actuation_receipt import canonical, chain_hash, content_hash, verify_chain


class DroppedWriteDriver(SpyDriver):
    def fill(self, selector, value):
        self.mutating.append(f"fill {selector}")


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


def reseal(path, edit):
    """Apply `edit` to the parsed records, then reseal every record with the chain
    rule, as an attacker who knows it would."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    edit(records)
    head, session = "", None
    for index, rec in enumerate(records):
        for key in ("content_hash", "_prev", "_hash"):
            rec.pop(key, None)
        if index and session:
            rec["session"] = session
        rec["content_hash"] = content_hash(rec)
        rec["_prev"] = head
        rec["_hash"] = chain_hash(head, rec)
        head = rec["_hash"]
        if index == 0:
            session = "sha256:" + rec["_hash"]
    path.write_text("".join(canonical(r) + "\n" for r in records), encoding="utf-8")


def mixed_session(w):
    """Acted, refused, and held steps in one session."""
    w.nav("/notes")
    w.fill("/notes", "Title", "weekly notes")
    w.nav("/login")
    w.fill("/login", "Password", PASSWORD, sid="pw")
    w.nav("/order")
    w.submit_order()


def run(w, level="verdict"):
    return rederive.rederive(w.receipts.path, w.evidence.root, level=level)


def record_for(report, seq):
    return next(r for r in report["records"] if r["seq"] == seq)


def test_untouched_session_matches_at_l0_to_l3(tmp_path, site):
    w = World(tmp_path, site)
    mixed_session(w)
    report = run(w)
    assert report["verdict"] == "MATCH", report
    assert {name: lvl["verdict"] for name, lvl in report["levels"].items()} == {
        "chain": "MATCH", "evidence": "MATCH", "policy": "MATCH", "verdict": "MATCH"}
    assert len(report["records"]) == 6
    statuses = [r["status"] for r in report["records"]]
    assert statuses == ["acted", "acted", "acted", "refused", "acted", "needs-human"]


def test_every_step_receipt_names_its_stored_inputs(tmp_path, site):
    w = World(tmp_path, site)
    mixed_session(w)
    for line in w.receipt_lines()[1:]:
        refs = line["evidence"]
        assert refs["inputs"].startswith("sha256:") and w.evidence.check(refs["inputs"]) == "MATCH"
        if line["execution"].get("acted"):
            assert w.evidence.check(refs["after"]) == "MATCH"


def test_missing_blob_is_unverifiable(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    w.fill("/notes", "Title", "weekly notes")
    after = w.receipt_lines()[-1]["evidence"]["after"]
    w.evidence.path_for(after).unlink()
    report = run(w)
    assert report["levels"]["evidence"]["verdict"] == "UNVERIFIABLE"
    assert record_for(report, 2)["verdict"] == "UNVERIFIABLE"
    assert report["verdict"] == "UNVERIFIABLE"


def test_edited_blob_is_drift(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    w.fill("/notes", "Title", "weekly notes")
    before = w.receipt_lines()[-1]["before"]["evidence"]
    path = w.evidence.path_for(before)
    path.write_bytes(path.read_bytes().replace(b"Scratch notes", b"Scratch nodes"))
    report = run(w, level="evidence")
    assert report["levels"]["evidence"]["verdict"] == "DRIFT" and report["verdict"] == "DRIFT"
    assert "policy" not in report["levels"]


def test_edited_rule_hit_is_drift_at_l2(tmp_path, site):
    w = World(tmp_path, site)
    mixed_session(w)

    def launder(records):
        held = records[-1]
        assert held["policy"]["outcome"] == "confirm"
        held["policy"]["outcome"] = "pass"
        held["policy"]["rule_hits"] = [h for h in held["policy"]["rule_hits"] if h["rule"] != "R7.irreversible"]
        held["status"] = "acted"
    reseal(w.receipts.path, launder)
    assert verify_chain(w.receipts.path)["verdict"] == "MATCH"  # the chain alone accepts it
    report = run(w)
    assert report["levels"]["policy"]["verdict"] == "DRIFT"
    assert record_for(report, 6)["policy"] == "DRIFT" and report["verdict"] == "DRIFT"


def test_edited_verdict_is_drift_at_l3(tmp_path, site):
    w = World(tmp_path, site, driver=DroppedWriteDriver())
    w.nav("/notes")
    assert w.fill("/notes", "Title", "weekly notes").verdict == "drift"

    def launder(records):
        records[-1]["verification"]["verdict"] = "verified"
    reseal(w.receipts.path, launder)
    assert verify_chain(w.receipts.path)["verdict"] == "MATCH"
    report = run(w)
    assert report["levels"]["policy"]["verdict"] == "MATCH"
    assert report["levels"]["verdict"]["verdict"] == "DRIFT" and record_for(report, 2)["verdict"] == "DRIFT"


def test_changed_policy_source_is_unverifiable_at_l2(tmp_path, site, monkeypatch):
    w = World(tmp_path, site)
    w.nav("/notes")
    w.fill("/notes", "Title", "weekly notes")
    real = rederive.current_sources

    def moved():
        return {**real(), "policy.py": "sha256:" + "0" * 64}
    monkeypatch.setattr(rederive, "current_sources", moved)
    report = run(w)
    assert report["levels"]["policy"]["verdict"] == "UNVERIFIABLE"
    assert report["levels"]["verdict"]["verdict"] == "MATCH"
    assert any("policy.py" in note for note in report["levels"]["policy"]["notes"])


def test_value_shape_refusal_stores_no_value_and_reads_unverifiable_at_l2(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/checkout")
    result = w.fill("/checkout", "Notes", CARD, sid="notes")
    assert result.status == "refused"
    assert CARD.encode() not in w.all_bytes() and CARD.replace(" ", "").encode() not in w.all_bytes()
    report = run(w)
    assert record_for(report, 2)["policy"] == "UNVERIFIABLE"
    assert any("withheld" in note for note in record_for(report, 2)["notes"])
    assert report["levels"]["verdict"]["verdict"] == "MATCH"


def test_secret_field_refusal_re_derives_without_its_value(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/login")
    w.fill("/login", "Password", PASSWORD, sid="pw")
    assert PASSWORD.encode() not in w.all_bytes()
    assert record_for(run(w), 2)["policy"] == "MATCH"


def test_a_challenge_stop_re_derives(tmp_path, site):
    w = World(tmp_path, site)
    w.driver.navigate(site.url("/captcha"))
    assert w.fill("/captcha", "Email", "ada@example.test").status == "stopped"
    w.nav("/notes")  # paused: stops without reading anything
    report = run(w)
    assert report["verdict"] == "MATCH", report


def test_session_without_an_evidence_store_is_unverifiable_past_l0(tmp_path, site):
    w = World(tmp_path, site, evidence=False)
    w.nav("/notes")
    report = rederive.rederive(w.receipts.path, tmp_path / "no-such-store", level="verdict")
    assert report["levels"]["chain"]["verdict"] == "MATCH"
    assert report["verdict"] == "UNVERIFIABLE"


def test_a_malformed_step_is_never_stored_and_reads_unverifiable_at_l2(tmp_path, site):
    """A malformed step may carry a secret, so nothing of it is stored: L1 has
    nothing to check and L2 cannot re-run the refusal, which it says."""
    w = World(tmp_path, site)
    raw = {"step_id": "bad", "action_kind": "web.fill", "target": "http://127.0.0.1/x", "args": {"value": PASSWORD}}
    assert w.pipe.run_step(raw).status == "refused"
    report = run(w)
    row = record_for(report, 1)
    assert (row["evidence"], row["policy"], row["verdict"]) == ("MATCH", "UNVERIFIABLE", "MATCH")
    assert PASSWORD.encode() not in w.all_bytes()


def test_a_challenge_raised_by_the_act_re_derives(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    assert w.nav("/captcha").verdict == "unverifiable"
    report = run(w)
    assert report["verdict"] == "MATCH", report


def test_genesis_pins_every_source_a_level_re_runs(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    pinned = set(w.receipt_lines()[0]["sources"])
    assert set(rederive.L2_SOURCES) | set(rederive.L3_SOURCES) <= pinned
