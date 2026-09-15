"""Actuation asked for by a remote caller -- the policy layer between an MCP tool
call and `AccountableSurface.actuate`.

Remote actuation now has three distinct operator surfaces: registry exposure,
write authority, and read authority. The registry is checked first, content is
parsed into inert action metadata, then grants are reloaded and matched for both
the action and every read phase needed to precondition, verify, and roll back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from accountable_surface.read_authority import grant_digest, select_read_envelope
from accountable_surface.registry import EffectorRegistry
from accountable_surface.remote_durable import run_authorized_remote_actuation
from accountable_surface.surface import AccountableSurface


@dataclass(frozen=True)
class _AuthorityState:
    grants: list[dict]
    reason: str = ""


class _StaticAuthority:
    def __init__(self, grants: list[dict]) -> None:
        self._grants = list(grants)

    def load_for_remote_call(self) -> _AuthorityState:
        return _AuthorityState(self._grants)

    def reload_and_confirm(self, selection: dict[str, Any]) -> str | None:
        return None


def _refused(reason: str, **extra: Any) -> dict[str, Any]:
    """A refusal that never reached an effector."""
    payload: dict[str, Any] = {
        "decision": "deny", "acted": False, "verified": False,
        "verdict": "refused-before-actuation", "rolled_back": False,
        "reasons": [reason], "certificate": {}, "journal_entry": None,
    }
    payload.update(extra)
    return payload


def _grant_for(grants: list[dict], action_kind: str) -> tuple[dict | None, list[str]]:
    """The single action grant this call runs under."""
    matching = [
        grant for grant in grants
        if action_kind in ((grant.get("scope") or {}).get("allowed_actions") or [])
    ]
    if not matching:
        return None, []
    if len(matching) > 1:
        return matching[0], [f"{len(matching)} grants name {action_kind!r}; the first one was used"]
    return matching[0], []


def _receipt(surface: AccountableSurface, outcome, notes: list[str], since: int) -> dict[str, Any]:
    """The journal entry for THIS call, and nothing else from the journal."""
    mine = [entry.to_dict() for entry in surface.journal[since:] if entry.kind == "actuation"]
    return {
        "decision": outcome.decision,
        "acted": outcome.acted,
        "verified": outcome.verified,
        "verdict": outcome.verdict,
        "rolled_back": outcome.rolled_back,
        "reasons": list(outcome.reasons) + notes,
        "certificate": outcome.certificate,
        "journal_entry": mine[-1] if mine else None,
    }


def actuate_impl(
    surface: AccountableSurface,
    authority: Any,
    registry: EffectorRegistry,
    action_kind: str,
    target: str,
    content: str,
    expected_digest: str | None = None,
    justification: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Act through an exposed effector, or say why not."""
    exposed = registry.get(action_kind)
    if exposed is None:
        return _refused(f"action_kind {action_kind!r} is not exposed by this server",
                        exposed_action_kinds=registry.action_kinds())
    try:
        payload = exposed.decode(content)
    except ValueError as exc:
        return _refused(f"content is not what {action_kind!r} accepts: {exc}")
    read_requests, reason = _read_requests(exposed, target, payload)
    if read_requests is None:
        return _refused(reason)
    store = _authority_store(authority)
    reason, protected_digest = _protected_path_reason(store, read_requests)
    if reason is not None:
        return _refused(reason)
    state = _load_for_actuation(store)
    grant, notes = _grant_for(state.grants, action_kind)
    if grant is None:
        return _refused(state.reason or f"no operator grant names {action_kind!r} -- default-deny; the model cannot self-authorize")
    envelope, reason = select_read_envelope(state.grants, read_requests)
    if envelope is None:
        return _refused(f"read authority denied: {reason}")
    return run_authorized_remote_actuation(
        surface, store, exposed, action_kind, target, payload, expected_digest,
        justification, idempotency_key, grant, notes, read_requests, envelope, protected_digest,
    )


def _authority_store(authority: Any) -> Any:
    if hasattr(authority, "load_for_remote_call"):
        return authority
    return _StaticAuthority(authority if isinstance(authority, list) else [])


def _load_for_actuation(store: Any):
    try:
        return store.load_for_remote_call(include_durable_revoked=True)
    except TypeError:
        return store.load_for_remote_call()


def _protected_path_reason(store: Any, read_requests: list[Any]) -> tuple[str | None, str]:
    if not hasattr(store, "protected_path_reason"):
        return None, ""
    return store.protected_path_reason([request.subject for request in read_requests])


def _read_requests(exposed: Any, target: str, payload: Any) -> tuple[list[Any] | None, str]:
    if exposed.describe_read is None or exposed.required_read_phases is None:
        return None, f"action_kind {exposed.action_kind!r} has no read-authority contract"
    try:
        phases = exposed.required_read_phases(payload)
        rid = uuid4().hex
        return [exposed.describe_read(target, payload, phase, f"{rid}:{phase}") for phase in phases], ""
    except ValueError as exc:
        return None, f"read authority cannot describe this target: {exc}"
