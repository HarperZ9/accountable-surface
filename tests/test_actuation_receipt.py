"""The actuation receipt: one hash-chained JSON line per step, genesis first.

Every step writes a receipt, including steps that were refused, held for a
person, or stopped. A receipt carries rule hits and digests and never a field
value; a value is represented by an HMAC under a per-session salt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from accountable_surface import actuation_receipt as ar

SRC = Path(__file__).resolve().parent.parent / "src" / "accountable_surface"


def _log(tmp_path):
    return ar.ReceiptLog(tmp_path / "receipts.jsonl")


def _body(i):
    return {"step": {"step_id": f"s{i}", "action_kind": "web.fill"},
            "policy": {"outcome": "refuse", "rule_hits": [{"rule": "R4.value-shape", "reason": "shape luhn"}]},
            "execution": {"acted": False}}


def _write(tmp_path, n=5):
    log = _log(tmp_path)
    for i in range(n):
        log.emit(_body(i))
    return log.path


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_genesis_comes_first_and_names_the_session(tmp_path):
    path = _write(tmp_path, 2)
    genesis, first, second = [json.loads(line) for line in _lines(path)]
    assert genesis["kind"] == "genesis" and genesis["seq"] == 0
    assert first["session"] == second["session"] == "sha256:" + genesis["_hash"]
    assert [first["seq"], second["seq"]] == [1, 2]


def test_untouched_chain_matches(tmp_path):
    result = ar.verify_chain(_write(tmp_path))
    assert result["verdict"] == "MATCH" and result["records"] == 6


def test_reopening_the_log_continues_the_chain(tmp_path):
    _write(tmp_path, 2)
    _log(tmp_path).emit(_body(9))
    result = ar.verify_chain(tmp_path / "receipts.jsonl")
    assert result["verdict"] == "MATCH" and result["records"] == 4


@pytest.mark.parametrize("attack", ["edit", "delete", "reorder", "truncate-genesis"])
def test_planted_edit_delete_reorder_read_drift(tmp_path, attack):
    path = _write(tmp_path)
    lines = _lines(path)
    if attack == "edit":
        rec = json.loads(lines[3])
        rec["policy"]["outcome"] = "pass"
        lines[3] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    elif attack == "delete":
        del lines[2]
    elif attack == "reorder":
        lines[2], lines[3] = lines[3], lines[2]
    else:
        del lines[0]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert ar.verify_chain(path)["verdict"] == "DRIFT"


def test_unparseable_or_missing_file_is_unverifiable(tmp_path):
    assert ar.verify_chain(tmp_path / "nope.jsonl")["verdict"] == "UNVERIFIABLE"
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    assert ar.verify_chain(bad)["verdict"] == "UNVERIFIABLE"


def test_a_resealed_edit_passes_the_chain_check(tmp_path):
    """Check the check: an attacker who knows the chain rule can rewrite and reseal
    a receipt, and the chain alone accepts it. Only re-deriving the decision from
    stored evidence (levels L2 and L3, not built yet) would catch this."""
    path = _write(tmp_path, 2)
    records = [json.loads(line) for line in _lines(path)]
    records[1]["policy"]["outcome"] = "pass"
    prev = records[0]["_hash"]
    for rec in records[1:]:
        rec["_prev"] = prev
        rec.pop("_hash")
        rec["content_hash"] = ar.content_hash(rec)
        rec["_hash"] = ar.chain_hash(prev, rec)
        prev = rec["_hash"]
    path.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
                    encoding="utf-8")
    assert ar.verify_chain(path)["verdict"] == "MATCH"


def test_receipts_carry_no_field_values(tmp_path):
    log = _log(tmp_path)
    secretish = "weekly notes for the Ashby account"
    log.emit({"step": {"value_hmac": log.value_hmac(secretish)}})
    raw = log.path.read_bytes()
    assert secretish.encode() not in raw
    assert hashlib.sha256(secretish.encode()).hexdigest().encode() not in raw
    assert log.value_hmac(secretish) == log.value_hmac(secretish)
    assert ar.ReceiptLog(tmp_path / "other.jsonl").value_hmac(secretish) != log.value_hmac(secretish)


def test_genesis_pins_policy_and_detector_digests(tmp_path):
    genesis = json.loads(_lines(_write(tmp_path, 1))[0])
    for name in ("policy.py", "plan.py", "tiers.py", "detectors/secrets.py", "detectors/challenge.py",
                 "detectors/irreversible.py", "detectors/injection.py"):
        text = (SRC / name).read_bytes().replace(b"\r\n", b"\n")  # stable across checkouts
        expected = "sha256:" + hashlib.sha256(text).hexdigest()
        assert genesis["sources"][name] == expected, name
    assert genesis["policy_digest"].startswith("sha256:") and genesis["salt_digest"].startswith("sha256:")
