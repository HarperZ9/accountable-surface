"""Durable-state wrapper around one authorized remote actuation."""

from __future__ import annotations

from typing import Any

from accountable_surface.authority_state import AuthorityStateError, grant_ref, request_fingerprint
from accountable_surface.effector import RefusedActuation
from accountable_surface.read_authority import AuthorizedRead, filesystem_target_for, grant_digest, select_read_envelope
from accountable_surface.surface import AccountableSurface


def run_authorized_remote_actuation(
    surface: AccountableSurface,
    store: Any,
    exposed: Any,
    action_kind: str,
    target: str,
    payload: Any,
    expected_digest: str | None,
    justification: str | None,
    idempotency_key: str | None,
    grant: dict[str, Any],
    notes: list[str],
    read_requests: list[Any],
    envelope: Any,
    protected_digest: str,
) -> dict[str, Any]:
    before_request = read_requests[0]
    effector_target = _effector_target(target, before_request)
    durable = _begin_durable(store, grant, action_kind, idempotency_key, _fingerprint(
        action_kind, effector_target, payload, expected_digest, justification, exposed.describe,
        grant, envelope.to_audit(), protected_digest,
    ))
    if isinstance(durable, dict):
        return _refused(durable["reason"], authority_state=durable)
    if durable is not None and not durable.allowed:
        return _durable_refusal(durable)
    current = _current_envelope_before_read(store, durable, read_requests, envelope)
    if isinstance(current, dict):
        return current
    envelope, before_decision = current
    return _act_with_durable_state(
        surface, store, exposed, action_kind, effector_target, payload, expected_digest,
        justification, grant, notes, before_request, before_decision, envelope, durable,
    )


def _current_envelope_before_read(store: Any, durable: Any, read_requests: list[Any], envelope: Any):
    if durable is not None:
        state = store.load_for_remote_call()
        envelope, reason = select_read_envelope(state.grants, read_requests)
        if envelope is None:
            flags = {"committed": False, "resolved": False}
            _release(store, durable, flags, reason)
            audit = durable.to_dict()
            audit.pop("reservation_id", None)
            audit["usage_counted"] = 0
            return _refused(f"read authority denied: {state.reason or reason}", authority_state=audit)
    before = envelope.decision_for(read_requests[0])
    if before is None:
        return _refused("read authority denied: before phase is absent")
    return envelope, before


def _act_with_durable_state(
    surface: AccountableSurface,
    store: Any,
    exposed: Any,
    action_kind: str,
    effector_target: str,
    payload: Any,
    expected_digest: str | None,
    justification: str | None,
    grant: dict[str, Any],
    notes: list[str],
    before_request: Any,
    before_decision: Any,
    envelope: Any,
    durable: Any,
) -> dict[str, Any]:
    before = exposed.effector.perceive(effector_target)
    flags = {"committed": False, "resolved": False}
    selection = {"action_kind": action_kind, "action_grant_digest": grant_digest(grant), "read_envelope": envelope}
    since = len(surface.journal)
    try:
        outcome = surface._actuate_with_authorized_read(
            exposed.effector, target=effector_target, content=payload, authorization=grant,
            authorized_before=AuthorizedRead(before_request, before_decision, before),
            read_envelope=envelope, expected_digest=expected_digest, justification=justification,
            confirm_authority=lambda: _confirm(store, selection, durable, grant, flags),
        )
    except RefusedActuation as exc:
        _release(store, durable, flags, str(exc))
        return _refused(f"the effector refused the plan before acting: {exc}")
    return _receipt(surface, outcome, notes, since, _finish(store, durable, flags, outcome, grant))


def _refused(reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision": "deny", "acted": False, "verified": False,
        "verdict": "refused-before-actuation", "rolled_back": False,
        "reasons": [reason], "certificate": {}, "journal_entry": None,
    }
    payload.update(extra)
    return payload


def _receipt(surface: AccountableSurface, outcome: Any, notes: list[str], since: int,
             authority_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    mine = [entry.to_dict() for entry in surface.journal[since:] if entry.kind == "actuation"]
    receipt = {
        "decision": outcome.decision, "acted": outcome.acted, "verified": outcome.verified,
        "verdict": outcome.verdict, "rolled_back": outcome.rolled_back,
        "reasons": list(outcome.reasons) + notes, "certificate": outcome.certificate,
        "journal_entry": mine[-1] if mine else None,
    }
    if authority_audit is not None:
        receipt["authority_state"] = authority_audit
    return receipt


def _begin_durable(store: Any, grant: dict[str, Any], action_kind: str, key: str | None, fingerprint: str):
    if not hasattr(store, "begin_remote_actuation"):
        return None
    try:
        return store.begin_remote_actuation(grant, action_kind, key, fingerprint)
    except AuthorityStateError as exc:
        return {"reason": str(exc)}


def _durable_refusal(decision: Any) -> dict[str, Any]:
    audit = decision.to_dict()
    if decision.reason == "idempotent-replay":
        return _refused(decision.reason, decision="replay-denied-new-action",
                        verdict="idempotent-replay", authority_state=audit)
    return _refused(decision.reason, authority_state=audit)


def _confirm(store: Any, selection: dict[str, Any], durable: Any, grant: dict[str, Any], flags: dict[str, bool]) -> str | None:
    reason = store.reload_and_confirm(selection)
    if reason is not None:
        _release(store, durable, flags, reason)
        return reason
    if durable is None:
        return None
    reason = store.commit_remote_actuation(durable.reservation_id, grant)
    flags["committed"] = reason is None
    flags["resolved"] = reason is not None
    return reason


def _release(store: Any, durable: Any, flags: dict[str, bool], reason: str) -> None:
    if durable is None or flags.get("committed") or flags.get("resolved"):
        return
    try:
        store.release_precommit(durable.reservation_id, reason)
        flags["resolved"] = True
    except AuthorityStateError:
        pass


def _finish(store: Any, durable: Any, flags: dict[str, bool], outcome: Any, grant: dict[str, Any]) -> dict[str, Any] | None:
    if durable is None:
        return None
    if flags.get("committed"):
        status = "succeeded" if outcome.acted and outcome.verified else "failed"
        store.finish_remote_actuation(durable.reservation_id, status, _outcome_digest(outcome))
    elif not flags.get("resolved"):
        _release(store, durable, flags, outcome.verdict)
    audit = durable.to_dict()
    audit.pop("reservation_id", None)
    if getattr(store, "authority_state", None) is not None:
        audit["usage_counted"] = store.authority_state.usage_for(grant)["counted"]
    else:
        audit["usage_counted"] = durable.usage_counted
    return audit


def _effector_target(target: str, before_request: Any) -> str:
    return filesystem_target_for(before_request) if before_request.observation_kind == "fs.bytes" else target


def _fingerprint(action_kind: str, target: str, payload: Any, expected_digest: str | None,
                 justification: str | None, exposed: str, grant: dict[str, Any], read_audit: dict[str, Any],
                 protected_digest: str) -> str:
    content = payload if isinstance(payload, bytes) else repr(payload).encode("utf-8")
    return request_fingerprint({
        "action_kind": action_kind, "target": target,
        "content_sha256": request_fingerprint(content), "expected_digest": expected_digest or "",
        "justification_sha256": request_fingerprint(justification or ""), "exposed": exposed,
        "grant_ref": grant_ref(grant), "action_grant_digest": grant_digest(grant),
        "read_audit": _stable_read_audit(read_audit), "protected_paths": protected_digest,
    })


def _stable_read_audit(read_audit: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "observation_kind": item.get("observation_kind"), "phase": item.get("phase"),
        "verdict": item.get("verdict"), "grant_digest": item.get("grant_digest"),
        "scope_digest": item.get("scope_digest"), "target_scope_digest": item.get("target_scope_digest"),
    } for item in read_audit.get("decisions", [])]


def _outcome_digest(outcome: Any) -> str:
    return request_fingerprint({
        "decision": outcome.decision, "acted": outcome.acted, "verified": outcome.verified,
        "verdict": outcome.verdict, "rolled_back": outcome.rolled_back, "reasons": list(outcome.reasons),
    })
