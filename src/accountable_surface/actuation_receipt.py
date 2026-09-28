"""The actuation receipt (`accountable-surface.actuation-receipt/v1`).

One JSON line per step, including steps that never acted: a refusal, a hold for
a person, and a stop are evidence too. The first line of a log is a genesis
record naming the accountable-surface version, the digests of the policy,
plan, tier, and detector sources, the policy digest, the clock source, and the
digest of the per-session salt. Every later record carries the genesis hash as
its session id.

Two seals, the constructions the repo already uses:

- `content_hash` over every field except itself and the chain fields;
- `_hash = sha256(_prev | canonical(record without _hash))`, so an edit breaks
  its own hash and a deletion or reorder breaks the `_prev` link.

Values never enter a receipt. `value_hmac` is an HMAC under a per-session salt
kept beside the log, because a bare hash of a short value can be reversed by
guessing. A value the policy refused as a secret gets no HMAC at all.

Limit: the chain proves the file was not edited after it was sealed. It does not
prove the decisions in it are right. A writer who knows the chain rule can
rewrite and reseal a record from the start; only re-deriving the policy decision
and the verdict from stored evidence would catch that, and that re-derivation
is not built yet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "accountable-surface.actuation-receipt/v1"
PINNED_SOURCES = ("policy.py", "plan.py", "tiers.py", "page_evidence.py", "actuation_receipt.py",
                  "detectors/secrets.py", "detectors/challenge.py", "detectors/irreversible.py",
                  "detectors/injection.py")
_CHAIN = ("_prev", "_hash")
_ROOT = Path(__file__).resolve().parent


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def content_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k not in _CHAIN and k != "content_hash"}
    return "sha256:" + hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def chain_hash(prev: str, record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "_hash"}
    return hashlib.sha256(f"{prev}|{canonical(body)}".encode("utf-8")).hexdigest()


def source_digests() -> dict:
    """sha256 of each pinned source, line endings normalised so a checkout with
    CRLF and one with LF pin the same code."""
    out = {}
    for name in PINNED_SOURCES:
        data = (_ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        out[name] = "sha256:" + hashlib.sha256(data).hexdigest()
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReceiptLog:
    """Append-only, hash-chained receipts for one actuation session file."""

    def __init__(self, path, *, clock=_now, salt_path=None) -> None:
        self.path = Path(path)
        self.salt_path = Path(salt_path) if salt_path else self.path.with_name(self.path.name + ".salt")
        self.clock = clock
        self._salt = self._load_salt()
        self._head, self._seq, self._session = self._resume()

    def _load_salt(self) -> bytes:
        if self.salt_path.exists():
            return self.salt_path.read_bytes()
        self.salt_path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(32)
        with open(self.salt_path, "xb") as handle:
            handle.write(salt)
        return salt

    def _resume(self) -> tuple[str, int, str | None]:
        if not self.path.exists():
            return "", -1, None
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return "", -1, None
        first, last = json.loads(lines[0]), json.loads(lines[-1])
        return last.get("_hash", ""), int(last.get("seq", len(lines) - 1)), "sha256:" + first.get("_hash", "")

    def value_hmac(self, value: str) -> str:
        return "hmac-sha256:" + hmac.new(self._salt, str(value).encode("utf-8"), hashlib.sha256).hexdigest()

    def _append(self, record: dict) -> dict:
        record["content_hash"] = content_hash(record)
        record["_prev"] = self._head
        record["_hash"] = chain_hash(self._head, record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical(record) + "\n")
        self._head, self._seq = record["_hash"], record["seq"]
        return record

    def _genesis(self) -> None:
        from accountable_surface import __version__
        from accountable_surface.policy import policy_digest

        record = {"schema": SCHEMA, "kind": "genesis", "seq": 0, "created_at": self.clock(),
                  "accountable_surface": __version__, "sources": source_digests(),
                  "policy_digest": policy_digest(), "clock": "system-utc",
                  "salt_digest": "sha256:" + hashlib.sha256(self._salt).hexdigest()}
        self._append(record)
        self._session = "sha256:" + record["_hash"]

    def emit(self, body: dict) -> dict:
        """Seal and append one step receipt. Writes the genesis first if needed."""
        if self._session is None:
            self._genesis()
        record = {"schema": SCHEMA, "kind": "step", "session": self._session, "seq": self._seq + 1,
                  "created_at": self.clock(), **body}
        return self._append(record)


def verify_chain(path) -> dict:
    """L0: every content_hash and _hash re-derives, every _prev links, genesis
    first. MATCH, DRIFT, or UNVERIFIABLE (missing or unparseable file)."""
    p = Path(path)
    if not p.exists():
        return {"verdict": "UNVERIFIABLE", "records": 0, "breaks": ["no receipts file"]}
    try:
        records = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except ValueError:
        return {"verdict": "UNVERIFIABLE", "records": 0, "breaks": ["a line does not parse"]}
    breaks, head = [], ""
    if not records or records[0].get("kind") != "genesis":
        breaks.append("the first record is not a genesis record")
    session = "sha256:" + records[0].get("_hash", "") if records else ""
    for index, rec in enumerate(records):
        if rec.get("_prev") != head:
            breaks.append(f"record {index}: _prev does not link")
        if rec.get("content_hash") != content_hash(rec) or rec.get("_hash") != chain_hash(rec.get("_prev", ""), rec):
            breaks.append(f"record {index}: seal does not re-derive")
        if index and (rec.get("session") != session or rec.get("seq") != index):
            breaks.append(f"record {index}: session or seq out of place")
        head = rec.get("_hash", "")
    return {"verdict": "DRIFT" if breaks else "MATCH", "records": len(records), "breaks": breaks}
