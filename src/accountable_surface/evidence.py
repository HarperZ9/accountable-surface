"""The content-addressed evidence store for actuation receipts.

A blob lives at `<root>/sha256/<first two hex>/<hex>`, and its name is the sha256
of its bytes, so a reader re-hashes a blob to learn whether it is the one a
receipt named: missing reads UNVERIFIABLE, edited reads DRIFT. JSON blobs are
stored in the same canonical form (sorted keys, tight separators) the receipts
and page digests use, so a page's evidence is stored under its own digest.

What goes in: the inputs the policy check read (the step, the before page, the
grant, the approval reference, the pauses, the time), and the after evidence
the verdict read (the driver's snapshot and the separate reader's page). What
never goes in: a value the policy refused as a secret, and the raw bytes of a
secret shape on screen. Page text is redacted when it is read; driver
snapshots are redacted here, before storage, by `redact_snapshot`.

The store is local operator state. It sits beside the receipts and is never
published; an export that carries it is a choice the operator makes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from accountable_surface.detectors import secrets
from accountable_surface.page_evidence import KEPT_ATTRS, Control, PageEvidence
from accountable_surface.pipeline_record import is_secret

_REF = re.compile(r"sha256:([0-9a-f]{64})")
SECRET_FIELD = "[redacted:secret-field]"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class EvidenceStore:
    def __init__(self, root) -> None:
        self.root = Path(root)

    def path_for(self, ref) -> Path:
        """The blob path for a well-formed ref. Anything else raises, so a ref read
        from a receipt never names a path outside the store."""
        match = _REF.fullmatch(ref) if isinstance(ref, str) else None
        if match is None:
            raise ValueError("not a sha256 evidence ref")
        hexd = match.group(1)
        return self.root / "sha256" / hexd[:2] / hexd

    def put_bytes(self, data: bytes) -> str:
        ref = "sha256:" + hashlib.sha256(data).hexdigest()
        path = self.path_for(ref)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return ref

    def put(self, value) -> str:
        return self.put_bytes(canonical(value))

    def check(self, ref) -> str:
        """MATCH when the blob re-hashes to its name, DRIFT when it does not,
        UNVERIFIABLE when the ref is malformed or the blob is missing."""
        try:
            path = self.path_for(ref)
        except ValueError:
            return "UNVERIFIABLE"
        if not path.is_file():
            return "UNVERIFIABLE"
        return "MATCH" if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == ref else "DRIFT"

    def load(self, ref):
        """The parsed blob, or None unless it re-hashes to its name."""
        if self.check(ref) != "MATCH":
            return None
        try:
            return json.loads(self.path_for(ref).read_bytes().decode("utf-8"))
        except ValueError:
            return None


def page_from_dict(data: dict | None) -> PageEvidence | None:
    """Rebuild page evidence from its stored dict; the digest re-derives."""
    if not isinstance(data, dict):
        return None
    controls = tuple(Control(c["ref"], c["tag"], c["role"], c["name"], c["input_type"],
                             tuple(sorted(c.get("attrs", {}).items(), key=lambda kv: _attr_order(kv[0]))),
                             bool(c["in_form"]), c["form_action"]) for c in data.get("controls", []))
    return PageEvidence(url=data["url"], http_status=int(data["http_status"]),
                        headers=tuple(sorted(data.get("headers", {}).items())), title=data.get("title", ""),
                        controls=controls, frames=tuple(tuple(f) for f in data.get("frames", [])),
                        markers=tuple(data.get("markers", [])), text=data.get("text", ""),
                        redactions=int(data.get("redactions", 0)), channel=data.get("channel", "html-parse"))


def _attr_order(key: str) -> int:
    return KEPT_ATTRS.index(key) if key in KEPT_ATTRS else len(KEPT_ATTRS)


def redact_snapshot(snapshot: dict) -> tuple[dict, int]:
    """A copy of a driver snapshot fit to store: secret shapes in every field value
    replaced, and the whole value of a field whose name marks it secret dropped.
    Returns the copy and the number of redactions."""
    out, count, fields = dict(snapshot), 0, {}
    for name, value in (snapshot.get("fields") or {}).items():
        probe = Control(f"snapshot:{name}", "input", "textbox", str(name), "", (), False, "")
        if secrets.field_markers(probe):
            fields[name], count = SECRET_FIELD, count + 1
            continue
        text, hits = secrets.redact(str(value)) if isinstance(value, str) else (value, 0)
        fields[name], count = text, count + hits
    if "fields" in snapshot:
        out["fields"] = fields
    return out, count


WITHHELD = "[withheld:R4]"


def stored_step(step, decision) -> dict:
    """The step as the evidence store keeps it. When R4 refused a secret, every
    argument value and the post-condition value are withheld, so the store never
    holds the secret; L2 then re-derives only the rules that do not read them."""
    data = step.to_dict()
    if not is_secret(decision):
        return data
    data["args"] = {k: WITHHELD for k in data["args"]}
    if isinstance(data.get("post_condition"), dict) and "value" in data["post_condition"]:
        data["post_condition"] = {**data["post_condition"], "value": WITHHELD}
    return data


def store_inputs(store, ctx, decision, *, grant, config) -> dict | None:
    """Everything policy.decide read, so L2 can re-run it offline: the step (its
    values withheld when R4 refused a secret), the before page, the grant, the
    approval reference, the pauses, the time, and the config."""
    if store is None:
        return None
    before = store.put(ctx.before.to_dict()) if ctx.before is not None else None
    grant_ref = store.put(grant) if grant is not None else None
    inputs = {"schema": "accountable-surface.policy-inputs/v1", "step": stored_step(ctx.step, decision),
              "value_withheld": is_secret(decision), "before": before, "grant": grant_ref,
              "approval": ctx.approval, "paused": sorted(ctx.paused), "now": ctx.now,
              "plan_reversible": ctx.reversible, "config": config}
    return {"inputs": store.put(inputs), "after": None}


def store_after(store, refs, *, snapshot, reader, outcome, error, timed_out=False) -> None:
    """What the verdict read: the redacted driver snapshot, the separate reader's
    page, the effector's own verify bit, and the error. Names it in `refs`."""
    if store is None or refs is None:
        return
    after = {"schema": "accountable-surface.after-evidence/v1", "driver": snapshot,
             "reader": store.put(reader.to_dict()) if reader is not None else None,
             "acted": bool(outcome and outcome.acted), "effector_verified": bool(outcome and outcome.verified),
             "error": error, "timed_out": timed_out}
    refs["after"] = store.put(after)
