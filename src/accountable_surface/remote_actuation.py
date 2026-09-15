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

from accountable_surface.effector import RefusedActuation
from accountable_surface.read_authority import (
    AuthorizedRead,
    filesystem_target_for,
    grant_digest,
    select_read_envelope,
)
from accountable_surface.registry import EffectorRegistry
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
) -> dict[str, Any]:
    """Act through an exposed effector, or say why not."""
    exposed = registry.get(action_kind)
    if exposed is None:
        return _refused(
            f"action_kind {action_kind!r} is not exposed by this server",
            exposed_action_kinds=registry.action_kinds(),
        )
    try:
        payload = exposed.decode(content)
    except ValueError as exc:
        return _refused(f"content is not what {action_kind!r} accepts: {exc}")
    read_requests, reason = _read_requests(exposed, target, payload)
    if read_requests is None:
        return _refused(reason)
    store = _authority_store(authority)
    state = store.load_for_remote_call()
    grant, notes = _grant_for(state.grants, action_kind)
    if grant is None:
        return _refused(state.reason or f"no operator grant names {action_kind!r} -- default-deny; the model cannot self-authorize")
    envelope, reason = select_read_envelope(state.grants, read_requests)
    if envelope is None:
        return _refused(f"read authority denied: {reason}")
    before_request = read_requests[0]
    before_decision = envelope.decision_for(before_request)
    if before_decision is None:
        return _refused("read authority denied: before phase is absent")
    effector_target = _effector_target(target, before_request)
    before = exposed.effector.perceive(effector_target)
    selection = {"action_kind": action_kind, "action_grant_digest": grant_digest(grant), "read_envelope": envelope}
    since = len(surface.journal)
    try:
        outcome = surface._actuate_with_authorized_read(
            exposed.effector, target=effector_target, content=payload, authorization=grant,
            authorized_before=AuthorizedRead(before_request, before_decision, before),
            read_envelope=envelope, expected_digest=expected_digest, justification=justification,
            confirm_authority=lambda: store.reload_and_confirm(selection),
        )
    except RefusedActuation as exc:
        return _refused(f"the effector refused the plan before acting: {exc}")
    return _receipt(surface, outcome, notes, since)


def _authority_store(authority: Any) -> Any:
    if hasattr(authority, "load_for_remote_call"):
        return authority
    return _StaticAuthority(authority if isinstance(authority, list) else [])


def _read_requests(exposed: Any, target: str, payload: Any) -> tuple[list[Any] | None, str]:
    if exposed.describe_read is None or exposed.required_read_phases is None:
        return None, f"action_kind {exposed.action_kind!r} has no read-authority contract"
    try:
        phases = exposed.required_read_phases(payload)
        rid = uuid4().hex
        return [exposed.describe_read(target, payload, phase, f"{rid}:{phase}") for phase in phases], ""
    except ValueError as exc:
        return None, f"read authority cannot describe this target: {exc}"


def _effector_target(target: str, before_request: Any) -> str:
    if before_request.observation_kind == "fs.bytes":
        return filesystem_target_for(before_request)
    return target
