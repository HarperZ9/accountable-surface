"""Re-derive an actuation session from its receipts and evidence, offline.

    L0 chain     every content_hash and _hash re-derives, every _prev links
    L1 evidence  every blob a receipt names exists and re-hashes to its name
    L2 policy    policy.decide re-run on the stored inputs gives the recorded
                 outcome, rule hits, tier, approval, and digests
    L3 verdict   the predicate and the challenge scan re-run on the stored after
                 evidence give the recorded verdict

Each level labels each receipt MATCH, DRIFT, or UNVERIFIABLE, and a level's label
is the worst over its receipts (DRIFT over UNVERIFIABLE over MATCH). A missing
blob is UNVERIFIABLE, never MATCH. When the source a level re-runs differs from
the digest the genesis record pinned, that level is UNVERIFIABLE, because the
re-run would check different code.

This module reads. It imports no effector and no driver, so a re-derivation
cannot act (the replay tests hold that by walking the import graph).

Limits: L2 and L3 catch a receipt rewritten and resealed by someone who knows
the chain rule. They do not catch a writer who forges the evidence blobs as
well; only a world re-read (L4, not built) compares against the subject itself.
A refusal R4 made on a value's shape cannot be re-derived, because the value is
never stored; that receipt reads UNVERIFIABLE at L2, which is the price of I8.
"""

from __future__ import annotations

import json
from pathlib import Path

from accountable_surface import actuation_receipt, plan, policy, predicates
from accountable_surface.detectors import challenge
from accountable_surface.evidence import EvidenceStore, page_from_dict
from accountable_surface.page_evidence import from_snapshot

LEVELS = ("chain", "evidence", "policy", "verdict")
RANK = {"MATCH": 0, "UNVERIFIABLE": 1, "DRIFT": 2}
L2_SOURCES = ("policy.py", "plan.py", "tiers.py", "page_evidence.py", "evidence.py", "detectors/secrets.py",
              "detectors/challenge.py", "detectors/irreversible.py", "detectors/injection.py")
L3_SOURCES = ("predicates.py", "page_evidence.py", "evidence.py", "detectors/challenge.py")
VALUE_RULES = ("R4.value-shape", "R4.upload", "R8.echo")


def current_sources() -> dict:
    return actuation_receipt.source_digests()


def worst(labels) -> str:
    return max(labels, key=RANK.__getitem__, default="MATCH")


def load_records(path: Path) -> list:
    try:
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, ValueError):
        return []


def _source_drift(genesis: dict, names) -> list[str]:
    pinned, now = genesis.get("sources") or {}, current_sources()
    return [f"{n} differs from the digest the genesis record pinned" for n in names if pinned.get(n) != now.get(n)]


# --- L1 ------------------------------------------------------------------------

def _schema_refusal(rec: dict) -> bool:
    hits = (rec.get("policy") or {}).get("rule_hits") or []
    return [h.get("rule") for h in hits] == ["R9.schema"] and not (rec.get("execution") or {}).get("acted")


def _l1(rec: dict, store: EvidenceStore) -> tuple[str, list]:
    refs = rec.get("evidence")
    if not isinstance(refs, dict) or not refs.get("inputs"):
        if _schema_refusal(rec):
            return "MATCH", []  # nothing was read or stored, and nothing is claimed
        return "UNVERIFIABLE", ["the receipt names no stored evidence"]
    labels, notes = [store.check(refs["inputs"])], []
    inputs = store.load(refs["inputs"]) or {}
    labels += [store.check(inputs[k]) for k in ("before", "grant") if inputs.get(k)]
    if (rec.get("before") or {}).get("evidence") != inputs.get("before") and inputs:
        labels.append("DRIFT")
        notes.append("the receipt's before digest is not the stored before evidence")
    if refs.get("after"):
        labels.append(store.check(refs["after"]))
        after = store.load(refs["after"]) or {}
        if after.get("reader"):
            labels.append(store.check(after["reader"]))
    elif rec.get("execution", {}).get("acted"):
        labels.append("UNVERIFIABLE")
        notes.append("the step acted and names no after evidence")
    label = worst(labels)
    if label != "MATCH" and not notes:
        notes.append("a referenced blob is missing" if label == "UNVERIFIABLE" else "a blob does not re-hash to its name")
    return label, notes


# --- L2 ------------------------------------------------------------------------

def _hits(rule_hits, skip=()) -> list:
    return [(h.get("rule"), h.get("outcome"), h.get("reason")) for h in rule_hits or [] if h.get("rule") not in skip]


def _redecide(inputs: dict, store: EvidenceStore):
    step = plan.step_from_dict(inputs["step"])
    before = page_from_dict(store.load(inputs["before"])) if inputs.get("before") else None
    grant = store.load(inputs["grant"]) if inputs.get("grant") else None
    return policy.decide(step, before, grant=grant, approval=inputs.get("approval"),
                         paused=frozenset(inputs.get("paused") or ()), now=inputs.get("now", ""),
                         plan_reversible=bool(inputs.get("plan_reversible", True)), config=inputs.get("config"))


def _compare_policy(recorded: dict, again, withheld: bool) -> tuple[str, list]:
    derived = again.to_dict()
    skip = VALUE_RULES if withheld else ()
    notes = []
    if _hits(recorded.get("rule_hits"), skip) != _hits(derived["rule_hits"], skip):
        notes.append("the rule hits do not re-derive")
    unconsumed = recorded.get("outcome") == "confirm" and derived["outcome"] == "pass" and recorded.get("approval") is None
    if recorded.get("outcome") != derived["outcome"] and not unconsumed:
        notes.append(f"outcome {recorded.get('outcome')!r} re-derives as {derived['outcome']!r}")
    for key in ("tier", "policy_digest"):
        if recorded.get(key) != derived[key]:
            notes.append(f"{key} does not re-derive")
    if not unconsumed and recorded.get("approval") != derived["approval"]:
        notes.append("the approval reference does not re-derive")
    if recorded.get("inputs_digest") is not None and recorded.get("inputs_digest") != derived["inputs_digest"]:
        notes.append("inputs_digest does not re-derive")
    return ("DRIFT", notes) if notes else ("MATCH", [])


def _l2(rec: dict, store: EvidenceStore) -> tuple[str, list]:
    inputs = store.load((rec.get("evidence") or {}).get("inputs"))
    if inputs is None:
        return "UNVERIFIABLE", ["no stored policy inputs (a malformed step is never stored)"]
    withheld = bool(inputs.get("value_withheld"))
    if withheld and any(h.get("rule") in VALUE_RULES for h in rec["policy"].get("rule_hits") or []):
        return "UNVERIFIABLE", ["a rule read the value, and the value is withheld (R4, never stored)"]
    try:
        again = _redecide(inputs, store)
    except (plan.PlanError, KeyError, TypeError, ValueError) as exc:
        return "UNVERIFIABLE", [f"the stored inputs do not load: {type(exc).__name__}"]
    return _compare_policy(rec["policy"], again, withheld)


# --- L3 ------------------------------------------------------------------------

def _reverdict(after: dict, post, store: EvidenceStore) -> str:
    driver = after.get("driver") or {}
    reader = page_from_dict(store.load(after["reader"])) if after.get("reader") else None
    challenged = bool(challenge.scan(from_snapshot(driver)) or (reader and challenge.scan(reader)))
    if after.get("acted"):
        pred = predicates.check(post, driver_after=driver, reader_after=reader)[0]
        verdict = predicates.meet(["verified" if after.get("effector_verified") else "drift", pred])
    else:
        verdict = "unverifiable" if after.get("error") or challenged else "not-acted"
    return "unverifiable" if challenged else verdict


def _l3(rec: dict, store: EvidenceStore) -> tuple[str, list]:
    recorded = (rec.get("verification") or {}).get("verdict")
    refs = rec.get("evidence") or {}
    if not refs.get("after"):
        if recorded == "not-acted" and not rec.get("execution", {}).get("acted"):
            return "MATCH", []
        return "UNVERIFIABLE", [f"verdict {recorded!r} names no after evidence"]
    after, inputs = store.load(refs["after"]), store.load(refs.get("inputs"))
    if after is None or inputs is None or (after.get("reader") and store.load(after["reader"]) is None):
        return "UNVERIFIABLE", ["the after evidence is missing or does not re-hash"]
    derived = _reverdict(after, (inputs.get("step") or {}).get("post_condition"), store)
    if derived != recorded:
        return "DRIFT", [f"verdict {recorded!r} re-derives as {derived!r}"]
    return "MATCH", []


# --- the report ----------------------------------------------------------------

def _level(name: str, steps: list, store: EvidenceStore, genesis: dict, rows: list) -> dict:
    check = {"evidence": _l1, "policy": _l2, "verdict": _l3}[name]
    moved = _source_drift(genesis, L2_SOURCES if name == "policy" else L3_SOURCES) if name != "evidence" else []
    labels, notes = [], list(moved)
    for rec, row in zip(steps, rows):
        label, why = ("UNVERIFIABLE", ["source moved"]) if moved else check(rec, store)
        row[name], row["notes"] = label, row["notes"] + why
        labels.append(label)
    return {"verdict": worst(labels), "notes": notes}


def rederive(receipts_path, evidence_root, *, level: str = "verdict") -> dict:
    """Run L0 up to `level` and return the per-level and per-receipt labels."""
    upto = LEVELS.index(level)
    path = Path(receipts_path)
    chain = actuation_receipt.verify_chain(path)
    report = {"levels": {"chain": {"verdict": chain["verdict"], "notes": chain["breaks"]}}, "records": []}
    records = load_records(path)
    genesis = records[0] if records and records[0].get("kind") == "genesis" else {}
    steps = [r for r in records if r.get("kind") == "step"]
    report["records"] = [{"seq": r.get("seq"), "step_id": (r.get("step") or {}).get("step_id"),
                          "status": r.get("status"), "notes": []} for r in steps]
    store = EvidenceStore(evidence_root)
    for name in LEVELS[1:upto + 1]:
        report["levels"][name] = _level(name, steps, store, genesis, report["records"])
    report["verdict"] = worst(lvl["verdict"] for lvl in report["levels"].values())
    return report
