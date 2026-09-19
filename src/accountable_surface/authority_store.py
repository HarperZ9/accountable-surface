"""Server-side operator grant loader with optional durable authority state."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from accountable_surface.authority_state import (
    AuthorityStateError,
    DurableAuthorityState,
    ReservationDecision,
    grant_digest,
    grant_ref,
)
from accountable_surface.protected_paths import ProtectedPaths
from accountable_surface.read_authority import active_operator_grants, select_read_decision

AUTHORITY_STATE_ENV = "ACCOUNTABLE_SURFACE_AUTHORITY_STATE"


@dataclass(frozen=True)
class AuthorityState:
    grants: list[dict]
    reason: str = ""


class AuthorityStore:
    """Server-internal grant loader. Remote callers never receive grant bodies."""

    def __init__(self, path_str: str | None = None, *, authority_state_path: str | None = None,
                 journal_path: str | None = None, busy_timeout: float = 1.0) -> None:
        self._path_str = path_str or os.environ.get("ACCOUNTABLE_SURFACE_GRANTS")
        self._state_path = authority_state_path or os.environ.get(AUTHORITY_STATE_ENV)
        self._journal_path = journal_path or os.environ.get("ACCOUNTABLE_SURFACE_JOURNAL")
        self._durable = DurableAuthorityState(self._state_path, busy_timeout=busy_timeout) if self._state_path else None
        self._protected = ProtectedPaths.from_config(
            grants_path=self._path_str, authority_state_path=self._state_path, journal_path=self._journal_path,
        )

    @property
    def grants_path(self) -> str | None:
        return self._path_str

    @property
    def authority_state_path(self) -> str | None:
        return self._state_path

    @property
    def authority_state(self) -> DurableAuthorityState | None:
        return self._durable

    def load_for_remote_call(self, *, include_durable_revoked: bool = False) -> AuthorityState:
        if not self._path_str:
            return AuthorityState([], "no operator grant is loaded -- default-deny")
        data, reason = _load_grant_json(self._path_str)
        if reason:
            return AuthorityState([], reason)
        grants, reason = _normalize_grants(data)
        if reason:
            return AuthorityState([], reason)
        active, reason = active_operator_grants(grants)
        if self._durable is None or not active or include_durable_revoked:
            return AuthorityState(active, reason)
        try:
            filtered = [grant for grant in active if not self._durable.is_revoked(grant)]
        except AuthorityStateError as exc:
            return AuthorityState([], str(exc))
        return AuthorityState(filtered, "" if filtered else "operator grant is durably revoked")

    def reload_and_confirm(self, selection: dict[str, Any]) -> str | None:
        state = self.load_for_remote_call()
        if not state.grants:
            return state.reason or "operator grant is no longer usable before mutation"
        action_kind, digest = selection.get("action_kind"), selection.get("action_grant_digest")
        action_ok = any(_grant_names_action(grant, action_kind) and grant_digest(grant) == digest for grant in state.grants)
        if not action_ok:
            return "operator action grant was revoked, expired, or replaced before mutation"
        for previous in getattr(selection.get("read_envelope"), "decisions", ()):  # read scopes still match.
            fresh = select_read_decision(state.grants, previous.request)
            if fresh.verdict != "allow" or fresh.grant_digest != previous.grant_digest:
                return "read authority was revoked, expired, or replaced before mutation"
            if fresh.scope_digest != previous.scope_digest:
                return "read authority scope changed before mutation"
        return None

    def protected_path_reason(self, subjects: Iterable[str]) -> tuple[str | None, str]:
        hit = self._protected.deny_subjects(subjects)
        if hit is None:
            return None, self._protected.digest()
        return f"protected authority path refused: {hit.requested}", self._protected.digest()

    def begin_remote_actuation(self, grant: dict[str, Any], action_kind: str, idempotency_key: str | None,
                               fingerprint: str) -> ReservationDecision | None:
        if self._durable is None:
            return None
        return self._durable.reserve(grant, action_kind, idempotency_key, fingerprint)

    def commit_remote_actuation(self, reservation_id: str | None, grant: dict[str, Any]) -> str | None:
        return self._durable.commit_to_act(reservation_id, grant) if self._durable else None

    def finish_remote_actuation(self, reservation_id: str | None, status: str, outcome_digest: str) -> None:
        if self._durable is not None:
            self._durable.finish(reservation_id, status, outcome_digest)

    def release_precommit(self, reservation_id: str | None, reason: str) -> None:
        if self._durable is not None and reservation_id:
            self._durable.release_precommit(reservation_id, reason)

    def record_revocation(self, grant: dict[str, Any], reason: str) -> str:
        if self._durable is None:
            raise AuthorityStateError("authority-state-not-configured")
        return self._durable.record_revocation(grant, reason)


def load_operator_grants(path_str: str | None = None) -> list[dict]:
    path_str = path_str or os.environ.get("ACCOUNTABLE_SURFACE_GRANTS")
    if not path_str:
        return []
    data, reason = _load_grant_json(path_str)
    if reason:
        return []
    grants, reason = _normalize_grants(data)
    return [] if reason else grants


def _load_grant_json(path_str: str) -> tuple[Any, str]:
    try:
        return json.loads(Path(path_str).read_text(encoding="utf-8")), ""
    except OSError:
        return None, "operator grant file is unreadable"
    except ValueError:
        return None, "operator grant file is invalid JSON"


def _normalize_grants(data: Any) -> tuple[list[dict], str]:
    if isinstance(data, dict):
        return [data], ""
    if isinstance(data, list) and all(isinstance(grant, dict) for grant in data):
        return data, ""
    return [], "operator grant file has wrong top-level type"


def _grant_names_action(grant: dict, action_kind: Any) -> bool:
    return action_kind in ((grant.get("scope") or {}).get("allowed_actions") or [])
