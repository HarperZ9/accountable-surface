#!/usr/bin/env python3
"""verify_journal.py -- a zero-dependency, standalone verifier for an accountable-
surface journal. Pure Python stdlib, no accountable_surface import. A stranger
holding only the JSONL journal file re-derives its hash chain offline:

    python verify_journal.py path/to/journal.jsonl

The journal is an append-only log, one compact JSON object per line, each carrying
{kind, summary, detail} plus the chain fields _prev and _hash. This re-reads the
file, rechains from the genesis anchor, and recomputes every entry hash. A flipped
byte in any recorded field snaps the chain, and a deleted or reordered entry breaks
the _prev linkage. It prints one verdict line and exits: 0 MATCH, 1 DRIFT (a hash
or linkage mismatch), 2 UNVERIFIABLE (the file is missing, unreadable, or holds a
line this verifier cannot re-derive into canonical content).

The recompute is copied from journal_chain.py; the verdict entry point in the tree
(Surface.verify_journal) is coupled to coherence_membrane, so it cannot run alone.
This file drops that coupling and re-derives only the chain, the load-bearing seal.
"""
import json
import sys

GENESIS = ""


def _entry_hash(prev, content):
    """The chain hash of an entry: sha256 over the previous hash and the entry's
    canonical {kind, summary, detail}. Deterministic and order-significant."""
    import hashlib
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev}|{canonical}".encode("utf-8")).hexdigest()


def _content(rec):
    """The {kind, summary, detail} a journal line round-trips, or None if the line
    lacks the required fields (corrupt: cannot be re-derived, not proven-drifted)."""
    if not isinstance(rec, dict) or "kind" not in rec or "summary" not in rec:
        return None
    return {"kind": rec["kind"], "summary": rec["summary"], "detail": rec.get("detail", {})}


def verify_journal(text):
    """Rechain the journal text from genesis. Returns (label, detail). DRIFT names the
    first entry whose stored hash or _prev linkage does not re-derive; UNVERIFIABLE
    names the first line that will not parse into canonical content."""
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
        content = _content(rec)
        if content is None:
            return "UNVERIFIABLE", f"entry {seq} is missing kind or summary"
        prev = rec.get("_prev")
        stored = rec.get("_hash")
        expected = _entry_hash(head, content)
        if not isinstance(stored, str):
            return "DRIFT", f"entry {seq} carries no _hash to re-derive"
        if prev != head:
            return "DRIFT", f"entry {seq} _prev does not link to the running chain head"
        if stored != expected:
            return "DRIFT", f"entry {seq} _hash does not re-derive from its fields"
        head = stored
        seq += 1
    return "MATCH", f"chain intact over {seq} entries"


def main(argv):
    if not argv:
        print("usage: python verify_journal.py <journal.jsonl>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"UNVERIFIABLE  cannot read {argv[0]}: {exc.strerror}")
        return 2
    label, detail = verify_journal(text)
    print(f"{label}  {detail}")
    return {"MATCH": 0, "DRIFT": 1}.get(label, 2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
