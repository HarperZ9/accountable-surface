"""Tests for the action-receipt receptor and its offline verifier.

Proves the receptor emits a conformant project-telos.action-receipt/v1 event, that a
receipt re-derives offline to MATCH, and that any tamper yields DRIFT -- both through
the in-tree `verify_receipts` and the standalone zero-dependency CLI a stranger runs.
A separate case shows the distinction the contract turns on: a receipt can honestly
RECORD a DRIFT action verdict while the receipt's OWN chain still re-derives MATCH.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from accountable_surface.action_receipt import (
    ActionReceiptReceptor,
    receipt_from_outcome,
    verify_receipts,
)
from accountable_surface.native_control_effector import (
    FakeNativeControlRunner,
    NativeControlListEffector,
)
from accountable_surface.surface import AccountableSurface

_CLOCK = "2026-09-19T12:00:00Z"
_IDEM = "idem-nc-test-1"
_ROOT = Path(__file__).resolve().parents[1]


def _completed_outcome():
    return SimpleNamespace(
        acted=True, verified=True, decision="allow", verdict="pass",
        before_digest="sha256:" + "aa" * 32, after_digest="sha256:" + "bb" * 32,
        certificate={"verdict": "verified", "oracle": "composed-v1"},
    )


def _emit_one(store, outcome, action_kind="native.device.ls", target="C:/tmp/fix"):
    event = receipt_from_outcome(
        outcome, action_kind=action_kind, target=target, args_hash="sha256:deadbeef",
        native_control_receipt={"schema": "project-telos.native-control/v1", "at": _CLOCK},
        idempotency_key=_IDEM, created_at=_CLOCK,
    )
    return ActionReceiptReceptor(store).emit(event), event


def test_receipt_has_contract_required_shape(tmp_path):
    _, event = _emit_one(tmp_path / "r.jsonl", _completed_outcome())
    assert event["schema"] == "project-telos.action-receipt/v1"
    assert event["verification"]["verdict"] == "MATCH"
    assert event["result"]["state"] == "completed"
    assert event["side_effect"]["class"] == "read"
    assert event["persistence"]["append_only"] is True
    assert event["compensation_ref"] is None
    assert event["receipts"][0]["hash"].startswith("sha256:")


def test_emit_returns_persistence_receipt(tmp_path):
    persistence, event = _emit_one(tmp_path / "r.jsonl", _completed_outcome())
    assert persistence["event_id"] == event["event_id"]
    assert persistence["action_id"] == event["action_id"]
    assert persistence["write_hash"] and persistence["storage_ref"]


def test_offline_verify_match(tmp_path):
    store = tmp_path / "r.jsonl"
    _emit_one(store, _completed_outcome())
    label, _ = verify_receipts(store.read_text(encoding="utf-8"))
    assert label == "MATCH"


def test_append_only_chain_over_two_receipts(tmp_path):
    store = tmp_path / "r.jsonl"
    _emit_one(store, _completed_outcome())
    _emit_one(store, _completed_outcome(), target="C:/tmp/fix2")
    label, detail = verify_receipts(store.read_text(encoding="utf-8"))
    assert label == "MATCH"
    assert "2 receipts" in detail


def test_tamper_content_yields_drift(tmp_path):
    store = tmp_path / "r.jsonl"
    _emit_one(store, _completed_outcome())
    tampered = store.read_text(encoding="utf-8").replace('"MATCH"', '"DRIFT"')
    label, _ = verify_receipts(tampered)
    assert label == "DRIFT"


def test_tamper_reorder_or_delete_yields_drift(tmp_path):
    store = tmp_path / "r.jsonl"
    _emit_one(store, _completed_outcome())
    _emit_one(store, _completed_outcome(), target="C:/tmp/fix2")
    lines = store.read_text(encoding="utf-8").splitlines()
    reordered = "\n".join([lines[1], lines[0]])  # swap the two receipts
    label, _ = verify_receipts(reordered)
    assert label == "DRIFT"


def test_unparseable_line_is_unverifiable(tmp_path):
    label, _ = verify_receipts("{not json}\n")
    assert label == "UNVERIFIABLE"


def test_standalone_cli_reports_match_then_drift(tmp_path):
    store = tmp_path / "r.jsonl"
    _emit_one(store, _completed_outcome())
    script = _ROOT / "verify_action_receipts.py"
    ok = subprocess.run([sys.executable, str(script), str(store)], capture_output=True, text=True)
    assert ok.returncode == 0 and "MATCH" in ok.stdout
    store.write_text(store.read_text(encoding="utf-8").replace('"completed"', '"failed"'), encoding="utf-8")
    bad = subprocess.run([sys.executable, str(script), str(store)], capture_output=True, text=True)
    assert bad.returncode == 1 and "DRIFT" in bad.stdout


# --- full loop: surface.actuate -> receipt, offline MATCH -----------------------

def _fixture_dir(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    return tmp_path


def _entries_from_disk(path):
    return [{"name": e.name, "type": "dir" if e.is_dir() else "file", "kb": 0} for e in os.scandir(path)]


def _nc_receipt(entries, ok=True):
    return {"schema": "project-telos.native-control/v1", "tool": "telos.native.control",
            "action": "device.ls", "target": ".", "ok": ok,
            "result": {"ok": ok, "path": ".", "entries": entries, "count": len(entries)},
            "background": True, "at": _CLOCK}


def _grant(actions):
    return {"authorization_version": "0.1", "receipt_id": "rcpt-nc-int", "kind": "authorization-grant",
            "principal": {"id": "operator-1", "role": "operator"}, "agent": {"id": "nc-agent"},
            "intent": "native-control read", "scope": {"allowed_actions": list(actions), "allowed_targets": []},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00", "revoked": False}


def test_full_loop_propose_to_receipt_match(tmp_path):
    fixture = _fixture_dir(tmp_path / "fix")
    runner = FakeNativeControlRunner(_nc_receipt(_entries_from_disk(fixture)))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    surface = AccountableSurface(journal_path=tmp_path / "journal.jsonl")
    outcome = surface.actuate(eff, target=str(fixture), content=[str(fixture)],
                              authorization=_grant(["native.device.ls"]))
    assert outcome.acted and outcome.verified

    store = tmp_path / "receipts.jsonl"
    event = receipt_from_outcome(
        outcome, action_kind=eff.action_kind, target=str(fixture), args_hash="sha256:deadbeef",
        native_control_receipt=eff.native_control_receipt(), idempotency_key=_IDEM, created_at=_CLOCK,
    )
    ActionReceiptReceptor(store).emit(event)
    assert event["verification"]["verdict"] == "MATCH"
    assert event["execution"]["external_request_id"].startswith("native-control:")
    label, _ = verify_receipts(store.read_text(encoding="utf-8"))
    assert label == "MATCH"
    # the surface journal is independently tamper-evident, too
    assert surface.verify_journal()["chain_ok"] is True


def test_drift_action_verdict_still_writes_an_intact_receipt(tmp_path):
    """The actuator drifts (understates the listing); the surface catches it, so the
    receipt honestly records verdict=DRIFT -- yet the RECEIPT's own chain re-derives
    MATCH. Action integrity and receipt integrity are separate claims."""
    fixture = _fixture_dir(tmp_path / "fix")
    understated = [e for e in _entries_from_disk(fixture) if e["name"] != "a.txt"]
    runner = FakeNativeControlRunner(_nc_receipt(understated))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    outcome = AccountableSurface().actuate(eff, target=str(fixture), content=[str(fixture)],
                                           authorization=_grant(["native.device.ls"]))
    assert outcome.acted and not outcome.verified

    store = tmp_path / "receipts.jsonl"
    event = receipt_from_outcome(
        outcome, action_kind=eff.action_kind, target=str(fixture), args_hash="sha256:deadbeef",
        native_control_receipt=eff.native_control_receipt(), idempotency_key=_IDEM, created_at=_CLOCK,
    )
    ActionReceiptReceptor(store).emit(event)
    assert event["verification"]["verdict"] == "DRIFT"
    assert event["result"]["state"] == "failed"
    label, _ = verify_receipts(store.read_text(encoding="utf-8"))
    assert label == "MATCH"  # the receipt of a drifted action is itself intact
