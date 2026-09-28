#!/usr/bin/env python3
"""verify_actuation.py -- a standalone, zero-dependency verifier for an
accountable-surface actuation session (accountable-surface.actuation-receipt/v1).
Pure Python stdlib, no accountable_surface import:

    python verify_actuation.py receipts.jsonl [--evidence DIR]

L0, always: every record's content_hash and _hash re-derive, every _prev links,
the first record is the genesis, and every step names that genesis as its
session with the next sequence number.

L1, with --evidence: every blob a step names (its policy inputs, its after
evidence, and the before page, grant, and reader page those name) exists under
DIR/sha256/<2 hex>/<hex> and re-hashes to its name, and the receipt's before
digest is the stored before page.

It prints one line and exits 0 MATCH, 1 DRIFT (something does not re-derive),
2 UNVERIFIABLE (something is missing or unreadable). Re-running the policy
decision and the verdict (L2 and L3) needs the package: `accountable-surface-
replay verify`. The construction is copied from actuation_receipt.py and
rederive.py so this file stands alone.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

RANK = {"MATCH": 0, "UNVERIFIABLE": 1, "DRIFT": 2}
REF = re.compile(r"sha256:([0-9a-f]{64})")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _content_hash(record):
    body = {k: v for k, v in record.items() if k not in ("_prev", "_hash", "content_hash")}
    return "sha256:" + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _chain_hash(prev, record):
    body = {k: v for k, v in record.items() if k != "_hash"}
    return hashlib.sha256(f"{prev}|{_canonical(body)}".encode("utf-8")).hexdigest()


def _worst(labels):
    return max(labels, key=RANK.__getitem__, default="MATCH")


def check_chain(records):
    """L0 over parsed records: (label, breaks)."""
    breaks, head = [], ""
    if not records or records[0].get("kind") != "genesis":
        breaks.append("the first record is not a genesis record")
    session = "sha256:" + records[0].get("_hash", "") if records else ""
    for index, rec in enumerate(records):
        if rec.get("_prev") != head:
            breaks.append(f"record {index}: _prev does not link")
        if rec.get("content_hash") != _content_hash(rec) or rec.get("_hash") != _chain_hash(rec.get("_prev", ""), rec):
            breaks.append(f"record {index}: seal does not re-derive")
        if index and (rec.get("session") != session or rec.get("seq") != index):
            breaks.append(f"record {index}: session or seq out of place")
        head = rec.get("_hash", "")
    return ("DRIFT" if breaks else "MATCH"), breaks


class Store:
    def __init__(self, root):
        self.root = Path(root)

    def check(self, ref):
        match = REF.fullmatch(ref) if isinstance(ref, str) else None
        if match is None:
            return "UNVERIFIABLE"
        path = self.root / "sha256" / match.group(1)[:2] / match.group(1)
        if not path.is_file():
            return "UNVERIFIABLE"
        return "MATCH" if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == ref else "DRIFT"

    def load(self, ref):
        if self.check(ref) != "MATCH":
            return None
        match = REF.fullmatch(ref)
        try:
            return json.loads((self.root / "sha256" / match.group(1)[:2] / match.group(1)).read_text(encoding="utf-8"))
        except ValueError:
            return None


def _schema_refusal(rec):
    hits = (rec.get("policy") or {}).get("rule_hits") or []
    return [h.get("rule") for h in hits] == ["R9.schema"] and not (rec.get("execution") or {}).get("acted")


def check_step_evidence(rec, store):
    """L1 for one step record, the same rule rederive._l1 applies."""
    refs = rec.get("evidence")
    if not isinstance(refs, dict) or not refs.get("inputs"):
        return "MATCH" if _schema_refusal(rec) else "UNVERIFIABLE"
    labels = [store.check(refs["inputs"])]
    inputs = store.load(refs["inputs"]) or {}
    labels += [store.check(inputs[k]) for k in ("before", "grant") if inputs.get(k)]
    if inputs and (rec.get("before") or {}).get("evidence") != inputs.get("before"):
        labels.append("DRIFT")
    if refs.get("after"):
        labels.append(store.check(refs["after"]))
        after = store.load(refs["after"]) or {}
        if after.get("reader"):
            labels.append(store.check(after["reader"]))
    elif (rec.get("execution") or {}).get("acted"):
        labels.append("UNVERIFIABLE")
    return _worst(labels)


def verify(path, evidence=None):
    try:
        records = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return "UNVERIFIABLE", f"cannot read {path}: {exc.strerror}"
    except ValueError:
        return "UNVERIFIABLE", "a line does not parse"
    label, breaks = check_chain(records)
    summary = f"chain {'intact' if not breaks else 'broken: ' + breaks[0]} over {len(records)} records"
    if evidence is None:
        return label, f"L0 only: {summary} (pass --evidence DIR for L1)"
    store = Store(evidence)
    steps = [r for r in records if r.get("kind") == "step"]
    step_labels = [check_step_evidence(r, store) for r in steps]
    bad = sum(1 for s in step_labels if s != "MATCH")
    return _worst([label] + step_labels), f"{summary}; evidence: {len(steps) - bad} of {len(steps)} steps re-hash"


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    evidence = None
    if "--evidence" in argv:
        at = argv.index("--evidence")
        if at + 1 >= len(argv):
            print("UNVERIFIABLE  --evidence needs a folder")
            return 2
        evidence = argv[at + 1]
    label, detail = verify(argv[0], evidence)
    print(f"{label}  {detail}")
    return {"MATCH": 0, "DRIFT": 1}.get(label, 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
