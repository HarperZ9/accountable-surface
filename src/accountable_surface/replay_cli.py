"""accountable-surface-replay: check an actuation session without acting.

    accountable-surface-replay verify  <receipts> [--evidence DIR] [--level chain|evidence|policy|verdict]
    accountable-surface-replay explain <receipts> --event SEQ [--evidence DIR]
    accountable-surface-replay export  <receipts> [--evidence DIR] --mode chain|full --out DIR

`verify` prints the level report as JSON and exits 0 MATCH, 1 DRIFT, 2
UNVERIFIABLE, as the two existing verifiers do. `explain` shows one event: the
step as a person may see it (no value), every rule hit with its reason, the
evidence refs, the verdict detail, and what re-derivation says about it.
`export --mode chain` writes the receipts alone, which reveal nothing about
values; `--mode full` adds the salt, every blob the receipts name, and the
pinned sources, so a stranger can re-derive L0 to L3.

Nothing here acts. The module imports no effector and no driver; a re-derivation
of the world itself (L4) is not built.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from accountable_surface import actuation_receipt, plan, rederive
from accountable_surface.evidence import EvidenceStore

EXIT = {"MATCH": 0, "DRIFT": 1}
EXPORT_SCHEMA = "accountable-surface.replay-export/v1"


def _print(value) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _verify(args) -> int:
    level = args.level or ("verdict" if args.evidence else "chain")
    if level != "chain" and not args.evidence:
        _print({"verdict": "UNVERIFIABLE", "error": f"level {level!r} needs --evidence DIR"})
        return 2
    report = rederive.rederive(args.receipts, args.evidence or ".", level=level)
    _print(report)
    return EXIT.get(report["verdict"], 2)


def _public_step(rec: dict, store: EvidenceStore | None) -> dict:
    inputs = store.load((rec.get("evidence") or {}).get("inputs")) if store else None
    shown = dict(rec.get("step") or {})
    if inputs and isinstance(inputs.get("step"), dict):
        try:
            shown.update(plan.render_public(plan.step_from_dict(inputs["step"])))
        except plan.PlanError:
            pass
    return shown


def _explain(args) -> int:
    records = rederive.load_records(Path(args.receipts))
    rec = next((r for r in records if r.get("kind") == "step" and r.get("seq") == args.event), None)
    if rec is None:
        _print({"error": f"no step event with seq {args.event}"})
        return 2
    store = EvidenceStore(args.evidence) if args.evidence else None
    level = "verdict" if store else "chain"
    report = rederive.rederive(args.receipts, args.evidence or ".", level=level)
    row = next((r for r in report["records"] if r["seq"] == args.event), {})
    policy = rec.get("policy") or {}
    _print({"seq": rec.get("seq"), "status": rec.get("status"), "step": _public_step(rec, store),
            "outcome": policy.get("outcome"), "rule_hits": policy.get("rule_hits"), "tier": policy.get("tier"),
            "approval": policy.get("approval"), "before": rec.get("before"), "after": rec.get("after"),
            "execution": rec.get("execution"), "verification": rec.get("verification"),
            "evidence": rec.get("evidence"), "message": rec.get("message"),
            "rederived": {k: row.get(k) for k in ("evidence", "policy", "verdict") if k in row}
            | {"chain": report["levels"]["chain"]["verdict"], "notes": row.get("notes", [])}})
    return 0


def _blob_refs(records: list, store: EvidenceStore) -> list[str]:
    refs = []
    for rec in records:
        for key in ("inputs", "after"):
            ref = (rec.get("evidence") or {}).get(key)
            if not ref:
                continue
            refs.append(ref)
            blob = store.load(ref) or {}
            refs += [blob[k] for k in ("before", "grant", "reader") if isinstance(blob.get(k), str)]
    return sorted(set(refs))


def _copy(src: Path, out: Path, rel: str, files: list) -> None:
    dest = out / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    files.append({"path": rel, "sha256": "sha256:" + hashlib.sha256(dest.read_bytes()).hexdigest()})


def _export_full(receipts: Path, records: list, store: EvidenceStore, out: Path, files: list, notes: list) -> None:
    salt = receipts.with_name(receipts.name + ".salt")
    if salt.is_file():
        _copy(salt, out, "receipts.jsonl.salt", files)
    else:
        notes.append("no salt file beside the receipts; value HMACs cannot be re-derived")
    for ref in _blob_refs(records, store):
        if store.check(ref) != "MATCH":
            notes.append(f"{ref} is missing or does not re-hash; not exported")
            continue
        hexd = ref.split(":", 1)[1]
        _copy(store.path_for(ref), out, f"evidence/sha256/{hexd[:2]}/{hexd}", files)
    pinned = (records[0].get("sources") or {}) if records else {}
    current = actuation_receipt.source_digests()
    for name, digest in sorted(pinned.items()):
        if current.get(name) != digest:
            notes.append(f"{name} moved since the session; not exported")
            continue
        dest = out / "sources" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((actuation_receipt.SOURCE_ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
        files.append({"path": f"sources/{name}", "sha256": digest})


def _export(args) -> int:
    out, receipts = Path(args.out), Path(args.receipts)
    if out.exists() and any(out.iterdir()):
        _print({"error": f"{out} is not empty; export writes only into a new or empty folder"})
        return 2
    if not receipts.is_file() or (args.mode == "full" and not args.evidence):
        _print({"error": "export needs the receipts file, and --evidence DIR for --mode full"})
        return 2
    records = rederive.load_records(receipts)
    files, notes = [], []
    _copy(receipts, out, "receipts.jsonl", files)
    if args.mode == "full":
        _export_full(receipts, records, EvidenceStore(args.evidence), out, files, notes)
    manifest = {"schema": EXPORT_SCHEMA, "mode": args.mode, "files": files, "notes": notes}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print(manifest)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="accountable-surface-replay",
                                     description="Check an actuation session without acting.")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="re-derive the session and exit by its verdict")
    verify.add_argument("receipts")
    verify.add_argument("--evidence")
    verify.add_argument("--level", choices=rederive.LEVELS)
    explain = sub.add_parser("explain", help="show one event and what re-derivation says about it")
    explain.add_argument("receipts")
    explain.add_argument("--event", type=int, required=True)
    explain.add_argument("--evidence")
    export = sub.add_parser("export", help="write a bundle a stranger can check")
    export.add_argument("receipts")
    export.add_argument("--evidence")
    export.add_argument("--mode", choices=("chain", "full"), required=True)
    export.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return {"verify": _verify, "explain": _explain, "export": _export}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
