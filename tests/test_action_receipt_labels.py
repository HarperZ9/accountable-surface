"""The action-receipt projection with its labels as parameters (D2).

`receipt_from_outcome` used to write native-control labels into every event:
the receptor name, the policy ref, the verification ref, and a `dir://` input
ref. Any effector can now emit a correctly labelled event, and the defaults
keep the native-control event byte-for-byte what it was (pinned below from the
code before the change).
"""

from __future__ import annotations

from types import SimpleNamespace

from accountable_surface.action_receipt import (
    ActionReceiptReceptor, canonical, receipt_from_outcome, verify_receipts,
)

CLOCK = "2026-09-27T00:00:00+00:00"
# content hash of the default native-control event, computed at d722e38 before
# the labels became parameters
PINNED_DEFAULT = "sha256:c6de039532b0ee1f54042bc54a8fc4f8a1ba4e71c307b74b5e3821ecc4482603"


def outcome():
    return SimpleNamespace(acted=True, verified=True, decision="allow", verdict="pass",
                           before_digest="sha256:" + "aa" * 32, after_digest="sha256:" + "bb" * 32,
                           certificate={"verdict": "verified", "oracle": "composed-v1"})


def native_event(**labels):
    return receipt_from_outcome(outcome(), action_kind="native.device.ls", target="C:/tmp/fix",
                                args_hash="sha256:deadbeef", idempotency_key="idem-1", created_at=CLOCK,
                                native_control_receipt={"schema": "project-telos.native-control/v1", "at": CLOCK},
                                **labels)


def web_event():
    return receipt_from_outcome(
        outcome(), action_kind="web.fill", target="http://127.0.0.1:8765/notes", args_hash="sha256:" + "cc" * 32,
        principal="agent:accountable-surface.pipeline", intent_ref="intent:fill-notes",
        idempotency_key="idem-2", created_at=CLOCK, side_effect_class="write",
        receptor={"name": "accountable-surface.web-receptor", "version": "0.1"},
        policy_ref="policy:accountable-actuation-v1", verification_ref="accountable-surface:page-readback",
        input_ref="http://127.0.0.1:8765/notes")


def test_default_native_control_event_is_byte_stable():
    assert native_event()["receipts"][0]["hash"] == PINNED_DEFAULT


def test_a_web_effector_emits_its_own_labels(tmp_path):
    event = web_event()
    assert event["component"]["name"] == "accountable-surface.web-receptor"
    assert event["policy"]["ref"] == "policy:accountable-actuation-v1"
    assert event["verification"]["ref"] == "accountable-surface:page-readback"
    assert event["input_materials"][0]["ref"] == "http://127.0.0.1:8765/notes"
    assert event["component"]["config_hash"] != native_event()["component"]["config_hash"]
    store = tmp_path / "r.jsonl"
    ActionReceiptReceptor(store).emit(event)
    assert verify_receipts(store.read_text(encoding="utf-8"))[0] == "MATCH"


def test_no_native_control_label_leaks_into_another_effector_event():
    assert "native-control" not in canonical(web_event())
    assert "dir://" not in canonical(web_event())


def test_a_changed_label_changes_the_content_hash():
    assert native_event(policy_ref="policy:other")["receipts"][0]["hash"] != native_event()["receipts"][0]["hash"]
