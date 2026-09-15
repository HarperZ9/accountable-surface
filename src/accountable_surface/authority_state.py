"""Stdlib-SQLite durable revocation, usage, idempotency, and recovery state."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

try:  # pragma: no cover - exercised only on Python builds without sqlite3.
    import sqlite3
except Exception:  # pragma: no cover
    sqlite3 = None  # type: ignore[assignment]


COUNTED = ("reserved", "committed", "succeeded", "failed", "ambiguous")
TERMINAL = ("succeeded", "failed", "denied_after_reservation", "released_precommit")


class AuthorityStateError(RuntimeError):
    """Authority DB cannot be trusted or reached, so remote mutation fails closed."""


@dataclass(frozen=True)
class ReservationDecision:
    allowed: bool
    reason: str
    reservation_id: str | None = None
    idempotency_digest: str | None = None
    terminal_status: str | None = None
    usage_counted: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class DurableAuthorityState:
    def __init__(self, path: str | Path, *, busy_timeout: float = 1.0) -> None:
        self.path = Path(path)
        self.busy_timeout = busy_timeout

    def reserve(self, grant: dict[str, Any], action_kind: str, idempotency_key: str | None,
                fingerprint: str, *, lease_seconds: int = 60) -> ReservationDecision:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return ReservationDecision(False, "idempotency-key-required")
        ref, digest, idem = grant_ref(grant), grant_digest(grant), _digest(idempotency_key)
        with self._transaction() as conn:
            existing = _one(conn, "SELECT * FROM operations WHERE idempotency_digest=?", idem)
            if existing is not None:
                return self._existing(existing, fingerprint, idem)
            if self._revoked(conn, ref):
                return ReservationDecision(False, "operator grant is durably revoked", idempotency_digest=idem)
            max_actions = grant_max_actions(grant)
            if max_actions is not None and _expired_reserved(conn, ref, _now()):
                return ReservationDecision(False, "authority-reservation-recovery-required", idempotency_digest=idem)
            counted = _counted(conn, ref)
            if max_actions is not None and counted >= max_actions:
                return ReservationDecision(False, "usage-exhausted", idempotency_digest=idem, usage_counted=counted)
            reservation_id = uuid4().hex
            lease = (_now_dt() + timedelta(seconds=lease_seconds)).isoformat()
            _insert_operation(conn, reservation_id, ref, digest, idem, fingerprint, action_kind, lease)
            return ReservationDecision(True, "reserved", reservation_id, idem, usage_counted=counted + 1)

    def commit_to_act(self, reservation_id: str | None, grant: dict[str, Any]) -> str | None:
        if not reservation_id:
            return "authority reservation is missing"
        with self._transaction() as conn:
            row = _one(conn, "SELECT * FROM operations WHERE reservation_id=?", reservation_id)
            if row is None:
                return "authority reservation is missing"
            if row["status"] != "reserved":
                return "authority reservation is not precommit"
            if self._revoked(conn, row["grant_ref"]):
                _status(conn, reservation_id, "denied_after_reservation", "sha256:revoked")
                return "operator grant is durably revoked before mutation"
            if row["grant_ref"] != grant_ref(grant) or row["grant_digest"] != grant_digest(grant):
                _status(conn, reservation_id, "denied_after_reservation", "sha256:changed")
                return "operator grant changed before mutation"
            _status(conn, reservation_id, "committed")
        return None

    def finish(self, reservation_id: str | None, status: str, outcome_digest: str) -> None:
        if reservation_id:
            terminal = "succeeded" if status == "succeeded" else "failed"
            with self._transaction() as conn:
                _status(conn, reservation_id, terminal, outcome_digest)

    def release_precommit(self, reservation_id: str, reason: str) -> None:
        with self._transaction() as conn:
            row = _one(conn, "SELECT * FROM operations WHERE reservation_id=?", reservation_id)
            if row is None or row["status"] != "reserved":
                raise AuthorityStateError("authority-recovery-refused")
            _status(conn, reservation_id, "released_precommit", _digest(reason))

    def mark_ambiguous(self, reservation_id: str, reason: str) -> None:
        with self._transaction() as conn:
            row = _one(conn, "SELECT * FROM operations WHERE reservation_id=?", reservation_id)
            if row is None or row["status"] != "committed":
                raise AuthorityStateError("authority-recovery-refused")
            _status(conn, reservation_id, "ambiguous", _digest(reason))

    def record_revocation(self, grant: dict[str, Any], reason: str) -> str:
        ref, digest, reason_digest = grant_ref(grant), grant_digest(grant), _digest(reason)
        with self._transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO revocations VALUES (?, ?, ?, ?)",
                (ref, digest, reason_digest, _now()),
            )
        return reason_digest

    def is_revoked(self, grant: dict[str, Any]) -> bool:
        with self._transaction() as conn:
            return self._revoked(conn, grant_ref(grant))

    def recovery_report(self) -> dict[str, int]:
        with self._transaction() as conn:
            return {
                "reserved_precommit": _status_count(conn, "reserved"),
                "committed_in_flight": _status_count(conn, "committed"),
                "ambiguous": _status_count(conn, "ambiguous"),
            }

    def usage_for(self, grant: dict[str, Any]) -> dict[str, int | str]:
        ref = grant_ref(grant)
        with self._transaction() as conn:
            return {"grant_ref": ref, "counted": _counted(conn, ref)}

    def _existing(self, row: Any, fingerprint: str, idem: str) -> ReservationDecision:
        if row["request_fingerprint"] != fingerprint:
            return ReservationDecision(False, "idempotency-conflict", row["reservation_id"], idem)
        status = row["status"]
        if status in ("succeeded", "failed"):
            return ReservationDecision(False, "idempotent-replay", row["reservation_id"], idem, status)
        if status == "reserved":
            reason = "authority-reservation-recovery-required" if row["lease_expires_at"] <= _now() else "operation-in-flight"
            return ReservationDecision(False, reason, row["reservation_id"], idem)
        if status in ("committed", "ambiguous"):
            return ReservationDecision(False, "operation-ambiguous", row["reservation_id"], idem)
        return ReservationDecision(False, "operation-already-resolved", row["reservation_id"], idem, status)

    def _revoked(self, conn: Any, ref: str) -> bool:
        return _one(conn, "SELECT grant_ref FROM revocations WHERE grant_ref=?", ref) is not None

    def _transaction(self):
        return _Transaction(self.path, self.busy_timeout)


class _Transaction:
    def __init__(self, path: Path, timeout: float) -> None:
        self.path, self.timeout, self.conn = path, timeout, None

    def __enter__(self):
        if sqlite3 is None:
            raise AuthorityStateError("sqlite-unavailable")
        try:
            _reject_unsupported_path(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, timeout=self.timeout)
            self.conn.row_factory = sqlite3.Row
            _verify(self.conn)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            _schema(self.conn)
            self.conn.execute("BEGIN IMMEDIATE")
            return self.conn
        except AuthorityStateError:
            raise
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise AuthorityStateError("authority-state-busy") from exc
            raise AuthorityStateError("authority-state-unverifiable") from exc
        except sqlite3.DatabaseError as exc:
            raise AuthorityStateError("authority-state-unverifiable") from exc

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.conn is not None:
                self.conn.rollback() if exc_type else self.conn.commit()
        finally:
            if self.conn is not None:
                self.conn.close()
        return False


def grant_ref(grant: dict[str, Any]) -> str:
    principal = grant.get("principal") if isinstance(grant.get("principal"), dict) else {}
    agent = grant.get("agent") if isinstance(grant.get("agent"), dict) else {}
    return "grant-ref:" + _digest({
        "authorization_version": grant.get("authorization_version"),
        "receipt_id": grant.get("receipt_id"),
        "principal_id": principal.get("id"),
        "agent_id": agent.get("id"),
        "nonce": grant.get("nonce", ""),
    }).split(":", 1)[1]


def grant_digest(grant: dict[str, Any]) -> str:
    return _digest(grant)


def request_fingerprint(value: Any) -> str:
    return _digest(value)


def grant_max_actions(grant: dict[str, Any]) -> int | None:
    for value in (grant.get("max_actions"), (grant.get("scope") or {}).get("max_actions")):
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _schema(conn: Any) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS revocations (grant_ref TEXT PRIMARY KEY, grant_digest TEXT, reason_digest TEXT, recorded_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS operations (idempotency_digest TEXT PRIMARY KEY, reservation_id TEXT UNIQUE, request_fingerprint TEXT, grant_ref TEXT, grant_digest TEXT, action_kind TEXT, usage_cost INTEGER, status TEXT, lease_expires_at TEXT, outcome_digest TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS operations_grant_status ON operations(grant_ref, status)")


def _verify(conn: Any) -> None:
    row = conn.execute("PRAGMA quick_check").fetchone()
    if row is not None and row[0] != "ok":
        raise AuthorityStateError("authority-state-unverifiable")


def _insert_operation(conn: Any, reservation_id: str, ref: str, digest: str, idem: str,
                      fingerprint: str, action_kind: str, lease: str) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (idem, reservation_id, fingerprint, ref, digest, action_kind, 1, "reserved", lease, None, now, now),
    )


def _status(conn: Any, reservation_id: str, status: str, outcome_digest: str | None = None) -> None:
    conn.execute(
        "UPDATE operations SET status=?, outcome_digest=?, updated_at=? WHERE reservation_id=?",
        (status, outcome_digest, _now(), reservation_id),
    )


def _one(conn: Any, query: str, *args: Any) -> Any:
    return conn.execute(query, args).fetchone()


def _counted(conn: Any, ref: str) -> int:
    marks = ",".join("?" for _ in COUNTED)
    return int(conn.execute(f"SELECT COUNT(*) FROM operations WHERE grant_ref=? AND status IN ({marks})", (ref, *COUNTED)).fetchone()[0])


def _expired_reserved(conn: Any, ref: str, now: str) -> bool:
    row = conn.execute("SELECT 1 FROM operations WHERE grant_ref=? AND status='reserved' AND lease_expires_at<=?", (ref, now)).fetchone()
    return row is not None


def _status_count(conn: Any, status: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM operations WHERE status=?", (status,)).fetchone()[0])


def _digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _reject_unsupported_path(path: Path) -> None:
    text = str(path)
    if text.startswith("\\\\") or os.path.normcase(text).startswith("//"):
        raise AuthorityStateError("authority-state-unsupported-path")
