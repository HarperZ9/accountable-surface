"""Typed read authority for remote actuation boundaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from accountable_surface.api_effector import ApiCall, ApiService
from accountable_surface.read_scopes import (
    describe_api_scope,
    describe_fs_scope,
    describe_web_scope,
    scope_matches,
)


@dataclass(frozen=True)
class ReadRequest:
    authority_class: str
    observation_kind: str
    subject: str
    phase: str
    target_scope: dict[str, Any]
    request_id: str
    requested_at: str


@dataclass(frozen=True)
class ReadDecision:
    request: ReadRequest
    verdict: str
    reasons: list[str]
    grant_digest: str | None = None
    scope_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request.request_id,
            "observation_kind": self.request.observation_kind,
            "phase": self.request.phase,
            "subject": self.request.subject,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "grant_digest": self.grant_digest,
            "scope_digest": self.scope_digest,
            "target_scope_digest": _digest(self.request.target_scope),
        }


@dataclass(frozen=True)
class AuthorizedRead:
    request: ReadRequest
    decision: ReadDecision
    observation: Any


@dataclass(frozen=True)
class ReadEnvelope:
    decisions: tuple[ReadDecision, ...]

    def decision_for(self, request: ReadRequest) -> ReadDecision | None:
        for decision in self.decisions:
            if decision.request.request_id == request.request_id:
                return decision
        return None

    def missing_phases(self, kind: str, subject: str, phases: Iterable[str]) -> list[str]:
        allowed = {
            d.request.phase for d in self.decisions
            if d.verdict == "allow" and d.request.observation_kind == kind and d.request.subject == subject
        }
        return [phase for phase in phases if phase not in allowed]

    def to_audit(self) -> dict[str, Any]:
        return {
            "decisions": [
                {
                    "request_id": decision.request.request_id,
                    "observation_kind": decision.request.observation_kind,
                    "phase": decision.request.phase,
                    "verdict": decision.verdict,
                    "grant_digest": decision.grant_digest,
                    "scope_digest": decision.scope_digest,
                    "target_scope_digest": _digest(decision.request.target_scope),
                }
                for decision in self.decisions
            ]
        }


def describe_filesystem_read(root: str | Path, target: str | Path, phase: str, request_id: str) -> ReadRequest:
    subject, root_key, rel_key = describe_fs_scope(root, target)
    return _request("fs.bytes", subject, phase, request_id, {"kind": "fs", "root": root_key, "path": rel_key})


def describe_web_read(subject: str, request_id: str) -> ReadRequest:
    origin, path = describe_web_scope(subject)
    return _request("web.document", subject, "direct", request_id, {"kind": "web", "origin": origin, "path": path})


def describe_api_read(service: ApiService, target: str, call: ApiCall, phase: str, request_id: str) -> ReadRequest:
    op = next((operation for operation in service.operations if operation.intent == call.intent), None)
    if op is None:
        raise ValueError(f"intent {call.intent!r} is not declared by {service.name}")
    subject, path = describe_api_scope(service, target, op.path_shape, op.intent)
    return _request(
        "api.resource", subject, phase, request_id,
        {"kind": "api", "service": service.name, "origin": service.origin,
         "intent": op.intent, "path": path, "path_shape": op.path_shape},
    )


def describe_journal_read(visibility: str, request_id: str) -> ReadRequest:
    if visibility not in {"own-call", "own-session", "session"}:
        raise ValueError(f"unknown journal visibility {visibility!r}")
    return _request(
        f"journal.{visibility}", f"journal://{visibility}", "direct", request_id,
        {"kind": "journal", "visibility": visibility},
    )


def filesystem_target_for(request: ReadRequest) -> str:
    if request.observation_kind != "fs.bytes" or not request.subject.startswith("file://"):
        raise ValueError("request is not a filesystem read request")
    return request.subject[len("file://"):]


def select_read_decision(grants: list[dict], request: ReadRequest) -> ReadDecision:
    if request.authority_class != "read":
        return _decision(request, "deny", "not a read-authority request")
    if request.observation_kind == "journal.own-session":
        return _decision(request, "needs-human", "journal.own-session is not bindable over stdio")
    for grant in grants:
        active, _reason = grant_is_active(grant)
        if not active:
            continue
        allowed = ((grant.get("scope") or {}).get("allowed_reads") or []) if isinstance(grant, dict) else []
        if not isinstance(allowed, list):
            continue
        for scope in allowed:
            if scope_matches(scope, request):
                return _decision(request, "allow", "read authority matched", grant, scope)
    return _decision(request, "deny", f"no read authority matches {request.observation_kind} {request.phase}")


def select_read_envelope(grants: list[dict], requests: Iterable[ReadRequest]) -> tuple[ReadEnvelope | None, str]:
    decisions = tuple(select_read_decision(grants, request) for request in requests)
    for decision in decisions:
        if decision.verdict != "allow":
            detail = "; ".join(decision.reasons) or "read authority denied"
            return None, f"missing read authority phase {decision.request.phase}: {detail}"
    return ReadEnvelope(decisions), ""


def active_operator_grants(grants: list[dict]) -> tuple[list[dict], str]:
    usable, reasons = [], []
    for grant in grants:
        active, reason = grant_is_active(grant)
        if active:
            usable.append(grant)
        else:
            reasons.append(reason)
    return (usable, "") if usable else ([], reasons[0] if reasons else "no operator grant is loaded -- default-deny")


def validate_authorized_read(auth: AuthorizedRead, envelope: ReadEnvelope, *, subject: str) -> str | None:
    if auth.decision.verdict != "allow":
        return "authorized read is not an allow decision"
    if envelope.decision_for(auth.request) != auth.decision:
        return "authorized read is not in the selected read envelope"
    observed_subject = getattr(auth.observation, "subject", None)
    if observed_subject != subject or auth.request.subject != subject:
        return "authorized read subject does not match this actuation target"
    return _validate_observation_digest(auth.observation, auth.request.observation_kind)


def _validate_observation_digest(observation: Any, observation_kind: str) -> str | None:
    if observation_kind not in {"fs.bytes", "api.resource"}:
        return None
    data = observation.data if isinstance(getattr(observation, "data", None), dict) else {}
    identity = data.get("sha256")
    if identity is None and observation_kind == "fs.bytes" and data.get("exists") is False:
        return None
    if not isinstance(identity, str):
        return "authorized read observation is missing a bound sha256 identity"
    digest = getattr(getattr(observation, "provenance", None), "digest", "")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    if identity != digest:
        return "authorized read observation sha256 does not match its witnessed digest"
    return None


def grant_digest(grant: dict) -> str:
    return _digest(grant)


def grant_is_active(grant: Any) -> tuple[bool, str]:
    if not isinstance(grant, dict):
        return False, "operator grant is malformed"
    if grant.get("kind") != "authorization-grant":
        return False, "operator grant is malformed: wrong kind"
    if not isinstance(grant.get("scope"), dict):
        return False, "operator grant scope is malformed"
    required = ("authorization_version", "receipt_id", "principal", "agent",
                "intent", "granted_at", "expires_at", "revoked")
    missing = [field for field in required if field not in grant]
    if missing:
        return False, "operator grant is malformed: missing " + ", ".join(missing)
    if not isinstance(grant.get("revoked"), bool):
        return False, "operator grant is malformed: revoked must be boolean"
    if grant.get("revoked") is True:
        return False, "operator grant is revoked"
    if not all(isinstance(grant.get(field), str) and grant.get(field) for field in (
        "authorization_version", "receipt_id", "intent", "granted_at", "expires_at",
    )):
        return False, "operator grant is malformed: required string field is empty"
    if not isinstance(grant.get("principal"), dict) or not isinstance(grant.get("agent"), dict):
        return False, "operator grant is malformed: principal and agent must be objects"
    try:
        granted_at = _parse_time(grant.get("granted_at"))
        expires_at = _parse_time(grant.get("expires_at"))
    except ValueError:
        return False, "operator grant time is malformed"
    now = datetime.now(timezone.utc)
    if granted_at and now < granted_at:
        return False, "operator grant is not yet active"
    if expires_at and now >= expires_at:
        return False, "operator grant is expired"
    return True, ""


def _request(kind: str, subject: str, phase: str, request_id: str, target_scope: dict[str, Any]) -> ReadRequest:
    return ReadRequest("read", kind, subject, phase, target_scope, request_id, datetime.now(timezone.utc).isoformat())


def _decision(request: ReadRequest, verdict: str, reason: str, grant: dict | None = None, scope: dict | None = None):
    return ReadDecision(request, verdict, [reason], grant_digest(grant) if grant else None, _digest(scope) if scope else None)


def _digest(value: Any) -> str:
    return "sha256:" + _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _sha(payload: bytes) -> str:
    from hashlib import sha256

    return sha256(payload).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("time must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
