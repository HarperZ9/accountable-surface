"""Pending approvals and target pauses, beside the durable authority state.

A policy `confirm` writes a pending approval: the step digest, the plan digest,
the before-evidence digest, a rendering of the step for a person, and an expiry.
The tool that hit `confirm` gets the approval id and the command a person runs.
It gets no token, and no tool can approve.

`approve` is called only by the operator CLI (`authority_cli.py`), after the
person typed the action verb and the target host at an interactive console. It
stores `token = HMAC-SHA256(key, canonical({approval_id, step_digest,
before_digest, expires_at, nonce}))`, keyed by a file beside the state database.
`live_for` and `consume` recompute the HMAC, so a row written straight into
SQLite without the key never passes, and `consume` marks it used in the same
transaction that checks it.

A policy `stop` on a challenge writes a pause for the target. Every later step on
that target stops until a person runs `accountable-surface-authority
clear-pause`, and both the pause and the clear land in `pause_log`.

Trust boundary: the token proves the approve command ran with the key. If the
agent runs as the same OS user with a shell, it could read the key file or
drive a console, so the token alone does not prove a person approved. Harness
deny rules for the approve command, the key path, and the state database, or an
approver on a separate account, close that gap. The receipt records the channel.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TTL_SECONDS = 600


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _canon(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS approvals (approval_id TEXT PRIMARY KEY, step_digest TEXT, plan_digest TEXT, "
    "before_digest TEXT, rendering TEXT, created_at TEXT, expires_at TEXT, status TEXT, token TEXT, nonce TEXT, "
    "approver TEXT, channel TEXT, decided_at TEXT, consumed_at TEXT)",
    "CREATE TABLE IF NOT EXISTS pauses (target TEXT PRIMARY KEY, reason TEXT, evidence_digest TEXT, paused_at TEXT)",
    "CREATE TABLE IF NOT EXISTS pause_log (target TEXT, action TEXT, by TEXT, reason TEXT, at TEXT)",
)


class ApprovalStore:
    def __init__(self, path, *, key_path=None, clock=utc_now, ttl_seconds: int = TTL_SECONDS) -> None:
        self.path = Path(path)
        self.key_path = Path(key_path) if key_path else self.path.with_name(self.path.name + ".approval-key")
        self.clock = clock
        self.ttl = ttl_seconds

    def now(self) -> str:
        return _iso(self.clock())

    def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=2.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        for statement in _SCHEMA:
            conn.execute(statement)
        return conn

    def _tx(self, work):
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = work(conn)
            conn.execute("COMMIT")
            return result
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # --- approvals -----------------------------------------------------------

    def request(self, step_digest: str, plan_digest: str, before_digest: str, rendering: dict) -> str:
        """Write (or reuse) the pending approval for this step on this page."""
        now = self.now()

        def work(conn):
            row = conn.execute("SELECT approval_id FROM approvals WHERE step_digest=? AND before_digest=? "
                               "AND status='pending' AND expires_at>=?", (step_digest, before_digest, now)).fetchone()
            if row is not None:
                return row["approval_id"]
            approval_id = "ap_" + uuid.uuid4().hex[:16]
            expires = _iso(self.clock() + timedelta(seconds=self.ttl))
            conn.execute("INSERT INTO approvals (approval_id, step_digest, plan_digest, before_digest, rendering, "
                         "created_at, expires_at, status) VALUES (?,?,?,?,?,?,?, 'pending')",
                         (approval_id, step_digest, plan_digest, before_digest, json.dumps(rendering, sort_keys=True),
                          now, expires))
            return approval_id
        return self._tx(work)

    def _public(self, row) -> dict:
        return {"approval_id": row["approval_id"], "step_digest": row["step_digest"],
                "before_digest": row["before_digest"], "rendering": json.loads(row["rendering"] or "{}"),
                "created_at": row["created_at"], "expires_at": row["expires_at"], "status": row["status"],
                "command": f"accountable-surface-authority approve --state {self.path} --approval-id {row['approval_id']}"}

    def pending(self) -> list[dict]:
        now = self.now()
        return self._tx(lambda c: [self._public(r) for r in c.execute(
            "SELECT * FROM approvals WHERE status='pending' AND expires_at>=? ORDER BY created_at", (now,))])

    def get(self, approval_id: str) -> dict | None:
        row = self._tx(lambda c: c.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone())
        return self._public(row) if row is not None else None

    def _key(self, create: bool) -> bytes | None:
        if self.key_path.exists():
            return self.key_path.read_bytes()
        if not create:
            return None
        key = os.urandom(32)
        with open(self.key_path, "xb") as handle:
            handle.write(key)
        return key

    def _token(self, key: bytes, row, nonce: str) -> str:
        body = {"approval_id": row["approval_id"], "step_digest": row["step_digest"],
                "before_digest": row["before_digest"], "expires_at": row["expires_at"], "nonce": nonce}
        return hmac.new(key, _canon(body), hashlib.sha256).hexdigest()

    def approve(self, approval_id: str, approver: str, channel: str = "cli-tty") -> dict:
        """Operator CLI only. Seals the pending approval with the HMAC token."""
        key, now = self._key(create=True), self.now()

        def work(conn):
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if row is None or row["status"] != "pending" or row["expires_at"] < now:
                raise ValueError("approval is not pending or has expired")
            nonce = uuid.uuid4().hex
            conn.execute("UPDATE approvals SET status='approved', token=?, nonce=?, approver=?, channel=?, "
                         "decided_at=? WHERE approval_id=?",
                         (self._token(key, row, nonce), nonce, approver, channel, now, approval_id))
            return self._public(row) | {"status": "approved"}
        return self._tx(work)

    def deny(self, approval_id: str, approver: str = "operator") -> None:
        self._tx(lambda c: c.execute("UPDATE approvals SET status='denied', approver=?, decided_at=? "
                                     "WHERE approval_id=? AND status='pending'", (approver, self.now(), approval_id)))

    def _valid(self, row, key, now) -> bool:
        if row is None or row["status"] != "approved" or row["consumed_at"] or row["expires_at"] < now:
            return False
        return hmac.compare_digest(self._token(key, row, row["nonce"] or ""), row["token"] or "")

    def _ref(self, row) -> dict:
        record = "sha256:" + hashlib.sha256(_canon({k: row[k] for k in row.keys() if k != "token"})).hexdigest()
        return {"approval_id": row["approval_id"], "step_digest": row["step_digest"],
                "before_digest": row["before_digest"], "expires_at": row["expires_at"], "status": "approved",
                "record": record, "channel": row["channel"], "approver": row["approver"]}

    def live_for(self, step_digest: str, before_digest: str) -> dict | None:
        """The live, HMAC-valid, unused approval for this step on this page."""
        key, now = self._key(create=False), self.now()
        if key is None:
            return None
        rows = self._tx(lambda c: c.execute("SELECT * FROM approvals WHERE step_digest=? AND before_digest=?",
                                            (step_digest, before_digest)).fetchall())
        live = [r for r in rows if self._valid(r, key, now)]
        return self._ref(live[0]) if live else None

    def consume(self, approval_id: str, step_digest: str, before_digest: str) -> bool:
        """Check and mark used in one transaction. False when anything differs."""
        key, now = self._key(create=False), self.now()
        if key is None:
            return False

        def work(conn):
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not self._valid(row, key, now) or row["step_digest"] != step_digest or row["before_digest"] != before_digest:
                return False
            conn.execute("UPDATE approvals SET consumed_at=? WHERE approval_id=?", (now, approval_id))
            return True
        return self._tx(work)

    # --- pauses --------------------------------------------------------------

    def pause(self, target: str, reason: str, evidence_digest: str) -> None:
        now = self.now()

        def work(conn):
            conn.execute("INSERT OR REPLACE INTO pauses VALUES (?,?,?,?)", (target, reason, evidence_digest, now))
            conn.execute("INSERT INTO pause_log VALUES (?,?,?,?,?)", (target, "pause", "policy", reason, now))
        self._tx(work)

    def paused_targets(self) -> frozenset:
        return frozenset(r["target"] for r in self._tx(lambda c: c.execute("SELECT target FROM pauses").fetchall()))

    def clear_pause(self, target: str, by: str, reason: str) -> bool:
        """Operator CLI only. The clear is itself recorded."""
        now = self.now()

        def work(conn):
            gone = conn.execute("DELETE FROM pauses WHERE target=?", (target,)).rowcount
            if gone:
                conn.execute("INSERT INTO pause_log VALUES (?,?,?,?,?)", (target, "clear", by, reason, now))
            return bool(gone)
        return self._tx(work)

    def pause_log(self) -> list[dict]:
        return self._tx(lambda c: [dict(r) for r in c.execute("SELECT * FROM pause_log ORDER BY rowid")])
