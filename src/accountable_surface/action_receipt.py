"""The action-receipt receptor -- the missing writer for `project-telos.action-receipt/v1`.

The action-receipt contract (telos/demo/integrations/action-receipt-conventions.json)
defines a durable, independently auditable event for agent work: proposed, admitted,
executed, failed, and compensated actions, each carrying a verification verdict
(MATCH / DRIFT / UNVERIFIABLE) and an append-only persistence rule. Until now nothing
on the runtime path emitted one. This module is that receptor: it turns an
`AccountableSurface.actuate` outcome into a conformant event and appends it to a
hash-chained, append-only store, so a stranger holding only the file can re-derive
the seal offline (`verify_receipts`).

Two independent seals, both re-derivable with stdlib only:
  * per-event content hash -- `receipts[].hash` over the event's semantic fields, so
    editing any field (target, verdict, decision, ...) breaks it.
  * chain hash -- `_hash = sha256(_prev | canonical(event))`, so deleting or reordering
    an event breaks the linkage. This is the same construction as the surface journal
    and `verify_journal.py`, applied to the exportable action-receipt stream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coherence_membrane.observation import sha256_hex

SCHEMA = "project-telos.action-receipt/v1"
RECEPTOR = {"name": "accountable-surface.native-control-receptor", "version": "0.1"}
GENESIS = ""


def canonical(value: Any) -> str:
    """Deterministic JSON: sorted keys, tight separators. The re-derivable form."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + sha256_hex(canonical(value).encode("utf-8"))


def _config_hash() -> str:
    return _digest({"schema": SCHEMA, "receptor": RECEPTOR})


def _outcome_terms(outcome: Any) -> tuple[str, str, str, str]:
    """Map an ActuationOutcome onto (event_type, result_state, stop_reason, verdict),
    using only the contract's typed vocabularies. Documented in docs/native-control-bridge.md."""
    acted = bool(getattr(outcome, "acted", False))
    verified = bool(getattr(outcome, "verified", False))
    decision = str(getattr(outcome, "decision", "deny"))
    verdict_status = str(getattr(outcome, "verdict", ""))
    if acted and verified:
        return "execution_completed", "completed", "completed", "MATCH"
    if acted and not verified:
        return "execution_failed", "failed", "tool_error", "DRIFT"
    if verdict_status == "refused-by-effector":
        return "execution_failed", "failed", "binding_failed", "UNVERIFIABLE"
    if decision == "deny":
        return "execution_failed", "cancelled", "policy_denied", "UNVERIFIABLE"
    if decision == "needs-human":
        return "execution_failed", "cancelled", "verification_unverifiable", "UNVERIFIABLE"
    return "execution_failed", "failed", "error", "UNVERIFIABLE"


def _external_request_id(nc: dict) -> str | None:
    if not nc:
        return None
    return f"native-control:{nc.get('at', '')}:{sha256_hex(canonical(nc).encode('utf-8'))[:16]}"


def _identity_block(base_id: str, idempotency_key: str, created_at: str, principal: str,
                    action_kind: str, args_hash: str, side_effect_class: str,
                    intent_ref: str, authority_ref: str | None, decision: str) -> dict:
    """The identity, component, action, and authority fields -- everything about WHO
    acted and under WHAT permission, before the execution facts are joined in."""
    return {
        "schema": SCHEMA,
        "event_id": f"evt_{base_id}",
        "action_id": f"act_{base_id}",
        "action_intent_id": f"intent_{base_id}",
        "idempotency_key": idempotency_key,
        "created_at": created_at,
        "agent": {"principal": principal},
        "component": {"name": RECEPTOR["name"], "version": RECEPTOR["version"], "config_hash": _config_hash()},
        "action": {"kind": action_kind, "side_effect_class": side_effect_class, "args_hash": args_hash},
        "intent_ref": intent_ref,
        "authority_ref": authority_ref,
        "policy": {"decision": decision, "ref": "policy:native-control-read-v1"},
    }


def _execution_block(state: str, idempotency_key: str, outcome: Any, nc: dict) -> dict:
    """The joinable execution facts: a durable external id, the idempotency key, the
    redacted before/after digests, and the native-control receipt's own digest."""
    return {
        "terminal_status": state,
        "external_request_id": _external_request_id(nc),
        "idempotency_key": idempotency_key,
        "redacted_before_ref": str(getattr(outcome, "before_digest", "")),
        "redacted_after_ref": str(getattr(outcome, "after_digest", "") or ""),
        "native_control_schema": nc.get("schema"),
        "native_control_receipt_digest": _digest(nc) if nc else None,
    }


def receipt_from_outcome(
    outcome: Any,
    *,
    action_kind: str,
    target: str,
    args_hash: str,
    native_control_receipt: dict | None = None,
    principal: str = "agent:accountable-surface.native-control",
    intent_ref: str = "intent:native-control-read",
    authority_ref: str | None = None,
    idempotency_key: str,
    created_at: str,
    side_effect_class: str = "read",
    reversible: bool = True,
) -> dict:
    """Build a `project-telos.action-receipt/v1` event from an actuation outcome.

    IDs are derived from the invocation and the injected `created_at`, so a fixed clock
    yields a byte-stable event. `receipts[].hash` is computed last, over every field
    except itself, so it seals the event's semantic content."""
    event_type, state, stop_reason, verdict = _outcome_terms(outcome)
    nc = native_control_receipt or {}
    base_id = sha256_hex(f"{action_kind}|{target}|{args_hash}|{created_at}".encode("utf-8"))[:24]
    before = str(getattr(outcome, "before_digest", ""))
    core = {
        **_identity_block(base_id, idempotency_key, created_at, principal, action_kind,
                          args_hash, side_effect_class, intent_ref, authority_ref,
                          str(getattr(outcome, "decision", "deny"))),
        "event_type": event_type,
        "input_materials": [{"ref": f"dir://{target}", "digest": before}],
        "side_effect": {"class": side_effect_class, "reversible": reversible},
        "execution": _execution_block(state, idempotency_key, outcome, nc),
        "evidence_ref": _digest({"before": before, "after": getattr(outcome, "after_digest", "")}),
        "verification": {"verdict": verdict, "ref": "accountable-surface:native-control-list"},
        "result": {"state": state, "stop_reason": stop_reason},
        "retry": {"attempt": 1, "max_attempts": 1},
        "compensation_ref": None,
        "persistence": {"append_only": True, "storage_ref": f"receipt:{action_kind}/evt_{base_id}"},
        "certificate": dict(getattr(outcome, "certificate", {}) or {}),
    }
    core["receipts"] = [{"kind": "content", "hash": _digest(core)}]
    return core


class ActionReceiptReceptor:
    """Append-only, hash-chained writer for action-receipt/v1 events. `emit` returns the
    persistence receipt the contract's receptor adapter promises: event_id, action_id,
    write_hash, and storage_ref."""

    def __init__(self, store_path: str | Path) -> None:
        self._path = Path(store_path)
        self._head = _chain_head(self._path)

    def emit(self, event: dict) -> dict:
        prev = self._head
        line_hash = sha256_hex(f"{prev}|{canonical(event)}".encode("utf-8"))
        record = {**event, "_prev": prev, "_hash": line_hash}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(canonical(record) + "\n")
        self._head = line_hash
        return {
            "event_id": event["event_id"],
            "action_id": event["action_id"],
            "write_hash": line_hash,
            "storage_ref": event["persistence"]["storage_ref"],
        }


def _chain_head(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return GENESIS
    head = GENESIS
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
            head = rec.get("_hash", head)
        except ValueError:
            continue
    return head


def verify_receipts(text: str) -> tuple[str, str]:
    """Re-derive the receipt stream offline. Returns (label, detail):
      MATCH        -- every content hash and chain link re-derives.
      DRIFT        -- a content hash or chain linkage does not re-derive (edit/reorder/delete).
      UNVERIFIABLE -- a line will not parse or is missing the fields to re-derive.
    Depends only on stdlib + the shared canonical form; a stranger with the file runs it."""
    head = GENESIS
    seq = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except ValueError:
            return "UNVERIFIABLE", f"line {seq} is not valid JSON"
        if not isinstance(rec, dict) or "_hash" not in rec or "receipts" not in rec:
            return "UNVERIFIABLE", f"entry {seq} is missing chain or receipt fields"
        event = {k: v for k, v in rec.items() if k not in ("_prev", "_hash")}
        core = {k: v for k, v in event.items() if k != "receipts"}
        try:
            stored_content = rec["receipts"][0]["hash"]
        except (KeyError, IndexError, TypeError):
            return "UNVERIFIABLE", f"entry {seq} carries no content hash to re-derive"
        if _digest(core) != stored_content:
            return "DRIFT", f"entry {seq} content hash does not re-derive from its fields"
        expected = sha256_hex(f"{head}|{canonical(event)}".encode("utf-8"))
        if rec.get("_prev") != head:
            return "DRIFT", f"entry {seq} _prev does not link to the running chain head"
        if rec.get("_hash") != expected:
            return "DRIFT", f"entry {seq} _hash does not re-derive from its fields"
        head = rec["_hash"]
        seq += 1
    return "MATCH", f"chain intact over {seq} receipts"
