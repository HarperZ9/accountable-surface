#!/usr/bin/env python3
"""verify_action_receipts.py -- a zero-dependency, standalone verifier for an
accountable-surface action-receipt store (project-telos.action-receipt/v1). Pure
Python stdlib, no accountable_surface import. A stranger holding only the JSONL file
re-derives its two seals offline:

    python verify_action_receipts.py path/to/action-receipts.jsonl

Each line is one append-only receipt carrying the event fields, a per-event content
hash in receipts[].hash (over every field except itself), and the chain fields _prev
and _hash. This re-reads the file, recomputes each content hash, and rechains from the
genesis anchor. A flipped byte in any recorded field breaks the content hash; a deleted
or reordered receipt breaks the _prev linkage. It prints one verdict line and exits:
0 MATCH, 1 DRIFT (a hash or linkage mismatch), 2 UNVERIFIABLE (a missing or unparseable
line). The re-derivation is copied from action_receipt.py so this file stands alone.
"""
import hashlib
import json
import sys

GENESIS = ""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def verify_receipts(text):
    """Rechain the receipt store from genesis and re-derive each content hash. DRIFT
    names the first receipt whose content hash or chain linkage does not re-derive;
    UNVERIFIABLE names the first line that will not parse or lacks the seal fields."""
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
        if not isinstance(rec, dict) or "_hash" not in rec or "receipts" not in rec:
            return "UNVERIFIABLE", f"entry {seq} is missing chain or receipt fields"
        event = {k: v for k, v in rec.items() if k not in ("_prev", "_hash")}
        core = {k: v for k, v in event.items() if k != "receipts"}
        try:
            stored_content = rec["receipts"][0]["hash"]
        except (KeyError, IndexError, TypeError):
            return "UNVERIFIABLE", f"entry {seq} carries no content hash to re-derive"
        if _digest(core) != stored_content:
            return "DRIFT", f"entry {seq} content hash does not re-derive from its fields"
        expected = hashlib.sha256(f"{head}|{_canonical(event)}".encode("utf-8")).hexdigest()
        if rec.get("_prev") != head:
            return "DRIFT", f"entry {seq} _prev does not link to the running chain head"
        if rec.get("_hash") != expected:
            return "DRIFT", f"entry {seq} _hash does not re-derive from its fields"
        head = rec["_hash"]
        seq += 1
    return "MATCH", f"chain intact over {seq} receipts"


def main(argv):
    if not argv:
        print("usage: python verify_action_receipts.py <action-receipts.jsonl>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        print(f"UNVERIFIABLE  cannot read {argv[0]}: {exc.strerror}")
        return 2
    label, detail = verify_receipts(text)
    print(f"{label}  {detail}")
    return {"MATCH": 0, "DRIFT": 1}.get(label, 2)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
