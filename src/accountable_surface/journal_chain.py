"""Tamper-evidence for the append-only journal: a hash chain over its entries.

The journal was corruption-evident (an unparseable line is counted) but not
tamper-evident: an edited-but-valid entry, a deleted middle entry, or a reordered
entry all still parse, so they passed silently. This chains each entry to the one
before it -- ``_hash = sha256(_prev | content)`` -- so any edit breaks its own hash,
and any delete or reorder breaks the ``_prev`` linkage. Reading the journal re-derives
the chain and counts every break, and ``verify_journal`` reports the verdict.

Self-contained (hashlib + json only); the entry content it hashes is exactly the
{kind, summary, detail} a JournalEntry round-trips, so the chain covers the detail
field (the decision, the provenance digests) the interoception digest alone did not.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GENESIS = ""


def entry_hash(prev: str, content: dict) -> str:
    """The chain hash of an entry: sha256 over the previous hash and the entry's
    canonical {kind, summary, detail}. Deterministic and order-significant."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev}|{canonical}".encode("utf-8")).hexdigest()


def read_journal(path: str | Path) -> dict:
    """Parse and chain-verify a persisted journal. Returns the valid entry contents,
    the count of corrupt/malformed lines (``replay_errors``), the count of chain breaks
    (``tamper_count`` -- an edited, deleted, or reordered entry), and the chain head so
    appends continue it. Corruption and tamper are counted separately, never conflated,
    and never silently dropped: a valid-but-tampered entry is still loaded, then flagged."""
    p = Path(path)
    records: list[dict] = []
    replay_errors = 0
    tamper_count = 0
    head = GENESIS
    if not p.exists():
        return {"records": records, "replay_errors": 0, "tamper_count": 0, "head": head}
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
            content = {"kind": rec["kind"], "summary": rec["summary"],
                       "detail": rec.get("detail", {})}
        except (ValueError, KeyError, TypeError):
            replay_errors += 1
            continue
        prev = rec.get("_prev") if isinstance(rec.get("_prev"), str) else None
        stored = rec.get("_hash") if isinstance(rec.get("_hash"), str) else None
        expected = entry_hash(prev if prev is not None else GENESIS, content)
        # a break: the linkage to the running head is wrong (delete/reorder), the stored
        # hash does not match the content (edit), or the chain fields are missing.
        if prev != head or stored is None or stored != expected:
            tamper_count += 1
        head = stored if stored is not None else expected
        records.append(content)
    return {"records": records, "replay_errors": replay_errors,
            "tamper_count": tamper_count, "head": head}
