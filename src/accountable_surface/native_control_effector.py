"""Cross-language efferent bridge -- drive telos native-control's SAFE read subset
from an accountable-surface effector.

`telos/demo/native-control.mjs` is a Node actuator over a browser (CDP), a native
app (UIA), and an OS device surface. It actuates today with its own receipt and a
hash-chained ledger, but UNGATED: anyone who can run the CLI actuates. This effector
puts one SAFE native-control verb behind the accountable-surface loop -- witnessed
perception, preview, gate `allow`, act (subprocess), re-perceive, verify, journal --
so the actuation is gated, bounded, and checked against an independent witness.

Slice 1 wires ONE read-only verb: `device ls` (list a directory). Its result is
independently witnessable: the surface lists the same directory with its own eyes
(`os.scandir`) and `verify` compares that witness against what native-control
reported. A read has no world effect to undo, so it is reversible by construction
and never escalates for irreversibility.

SAFE SUBSET ONLY. `NativeControlRunner` refuses any `(domain, verb)` outside
`SAFE_READ_VERBS`. The evasion and mass-outreach verbs (captcha, behave stealth,
network token, gmail send, linkedin post, scrape targets, mass autofill) and the
mutating device verbs (`device exec`, `device write`) are unreachable through this
bridge by construction -- there is no argument a caller can pass to reach them. The
write-class contract (with a compensation path) is defined in `NativeControlWriteEffector`
and is deliberately not yet exercised. See docs/native-control-bridge.md.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex

from accountable_surface.effector import Plan, RefusedActuation, Verdict

# The only native-control verbs this bridge will invoke. Every entry is read-only
# and side-effect-free. Anything not listed is refused before a subprocess spawns.
SAFE_READ_VERBS: frozenset[tuple[str, str]] = frozenset(
    {
        ("device", "ls"),  # list a directory -- slice 1, wired + tested + live-proven
    }
)

# Read verbs safe in principle but NOT yet wired here: still refused by the runner
# until each has its own independent-witness `verify`. `device read` is held back
# because the actuator over-serializes a PowerShell string's note-properties (see the
# design note). Named so the boundary between wired and target is explicit.
SAFE_READ_VERBS_TARGET: frozenset[tuple[str, str]] = frozenset(
    {("device", "read"), ("browser", "gettext"), ("browser", "snapshot-text"),
     ("app", "tree"), ("app", "value")}
)


def _canonical(value: Any) -> str:
    """Deterministic JSON: sorted keys, tight separators. Shared shape with the
    journal and the receptor, so a digest re-derives identically anywhere."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _entry_fingerprint(entries: list[dict]) -> list[str]:
    """A stable, size-independent fingerprint of a directory listing: the sorted
    set of ``type:name`` strings. Size/kb is deliberately excluded -- it is not
    stable across the two witnesses and is not what the listing asserts."""
    return sorted(f"{str(e.get('type'))}:{str(e.get('name'))}" for e in entries)


class NativeControlRunner:
    """Real runner: invoke native-control.mjs as a subprocess and return its parsed
    receipt. No shell, argv only. Refuses any verb outside `SAFE_READ_VERBS`."""

    def __init__(self, script_path: str | Path, *, node: str = "node", timeout: int = 30) -> None:
        self._script = str(Path(script_path))
        self._node = node
        self._timeout = timeout

    def run(self, domain: str, verb: str, params: list[str]) -> dict:
        if (domain, verb) not in SAFE_READ_VERBS:
            raise RefusedActuation(
                f"native-control verb {domain}.{verb!r} is not in the safe read allowlist"
            )
        argv = [self._node, self._script, domain, verb, *[str(p) for p in params]]
        proc = subprocess.run(  # noqa: S603 (argv only, no shell; verb allowlisted above)
            argv, capture_output=True, text=True, timeout=self._timeout, shell=False
        )
        text = proc.stdout.strip()
        if not text:
            raise RefusedActuation(f"native-control produced no receipt (stderr: {proc.stderr[:200]})")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RefusedActuation(f"native-control receipt is not JSON: {exc}") from exc


class FakeNativeControlRunner:
    """Test runner: returns a canned native-control receipt (or one per call) and
    records every invocation, so the accountability logic is testable offline
    without spawning Node. Enforces the same safe allowlist as the real runner."""

    def __init__(self, receipt: dict | list[dict]) -> None:
        self._receipts = receipt if isinstance(receipt, list) else [receipt]
        self._i = 0
        self.calls: list[tuple[str, str, list[str]]] = []

    def run(self, domain: str, verb: str, params: list[str]) -> dict:
        if (domain, verb) not in SAFE_READ_VERBS:
            raise RefusedActuation(
                f"native-control verb {domain}.{verb!r} is not in the safe read allowlist"
            )
        self.calls.append((domain, verb, list(params)))
        receipt = self._receipts[min(self._i, len(self._receipts) - 1)]
        self._i += 1
        return receipt


class NativeControlListEffector:
    """Gate `device ls` (list a directory) through the accountable-surface loop.

    Inert until authorized. Acts ONLY on a gate `allow` for the exact plan, only
    within a construction-bounded root, and self-verifies against an INDEPENDENT
    witness: the surface lists the same directory itself and `verify` compares that
    witness against native-control's reported listing. This closes the gap the
    `CommandEffector` documents -- there a verify reads only the actor's own account;
    here the read is checked against the surface's own eyes."""

    name = "native-control-list-effector"

    def __init__(self, runner: Any, *, allowed_root: str | Path, domain: str = "device", verb: str = "ls") -> None:
        if (domain, verb) not in SAFE_READ_VERBS:
            raise ValueError(f"{domain}.{verb} is not a wired safe read verb")
        self._runner = runner
        self._domain = domain
        self._verb = verb
        self.action_kind = f"native.{domain}.{verb}"
        self._root = Path(allowed_root).resolve()
        self._last: dict = {}

    def bound(self) -> dict:
        """The construction bound a gate allow can never travel outside of: the
        directory root this effector may list. `root` is a path facet, so a grant's
        `allowed_bounds` can cover it by ancestry (see bounds.py)."""
        return {"kind": "native-control", "root": self._root.as_posix()}

    def perceive(self, target: str) -> Observation:
        """An INDEPENDENT witness of the directory: the surface's own listing. This
        is the reference `verify` checks native-control's report against."""
        path = Path(target)
        exists = path.is_dir()
        entries: list[dict] = []
        if exists:
            for entry in os.scandir(path):
                entries.append({"name": entry.name, "type": "dir" if entry.is_dir() else "file"})
        fingerprint = _entry_fingerprint(entries)
        payload = _canonical({"dir": path.as_posix(), "entries": fingerprint}).encode("utf-8")
        return Observation(
            organ=self.name,
            subject=f"dir://{target}",
            summary=f"directory {'present' if exists else 'absent'} ({len(entries)} entries)",
            status=Status.PASS,
            provenance=Provenance.witness_bytes(f"dir://{target}", payload, "high"),
            data={"exists": exists, "count": len(entries), "sha256": sha256_hex(payload) if exists else None},
        )

    def preview(self, target: str, content: Any, before: Observation | None = None) -> Plan:
        """Describe the intended read. `content` is the verb's params (here, the path);
        binding it into the plan means the gate authorizes THIS exact invocation."""
        content_sha = sha256_hex(_canonical(list(content or [target])).encode("utf-8"))
        existed = bool(before.data.get("exists")) if before is not None else Path(target).is_dir()
        digest = "sha256:" + sha256_hex(f"{self.action_kind}|{target}|{content_sha}".encode("utf-8"))
        # A read has no world effect to undo, so it is reversible (rollback is the
        # identity) and never escalates to needs-human for irreversibility.
        return Plan(self.action_kind, target, content_sha, True, existed, digest)

    def act(self, plan: Plan, allow_receipt: Any, content: Any) -> Observation:
        """Run `device ls` via native-control -- only on a gate allow for THIS plan,
        only within the bound. Stores native-control's reported listing for `verify`."""
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow -- the effector will not run anything")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        if sha256_hex(_canonical(list(content or [plan.target])).encode("utf-8")) != plan.content_sha256:
            raise RefusedActuation("params do not match the previewed (authorized) plan")
        if not self._within_root(plan.target):
            raise RefusedActuation(f"target is outside the effector's bound: {self._root}")
        self._last = {}
        receipt = self._runner.run(self._domain, self._verb, [plan.target])
        result = receipt.get("result", {}) if isinstance(receipt, dict) else {}
        entries = result.get("entries", []) if isinstance(result, dict) else []
        actuator_fp = _entry_fingerprint(entries if isinstance(entries, list) else [])
        self._last = {
            "receipt": receipt,
            "actuator_ok": bool(receipt.get("ok")) and bool(result.get("ok")),
            "actuator_sha256": sha256_hex(_canonical(actuator_fp).encode("utf-8")),
            "actuator_count": len(actuator_fp),
        }
        return self.perceive(plan.target)

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        """Independent-witness check: does native-control's listing match the
        directory as the surface itself sees it?"""
        if not self._last.get("actuator_ok"):
            return Verdict("failed", "native-control reported an unsuccessful read")
        witness = _entry_fingerprint(
            [{"name": e.name, "type": "dir" if e.is_dir() else "file"} for e in os.scandir(plan.target)]
        )
        witness_sha = sha256_hex(_canonical(witness).encode("utf-8"))
        if self._last.get("actuator_sha256") == witness_sha:
            return Verdict("pass", "native-control listing matches the surface's independent directory witness")
        return Verdict("failed", "native-control listing does NOT match the independent witness (drift)")

    def rollback(self, plan: Plan) -> Observation:
        """A read has no world state to restore. Rollback is the identity re-perception;
        it exists so a failed-verify read still resolves cleanly through the surface."""
        return self.perceive(plan.target)

    def native_control_receipt(self) -> dict:
        """The last native-control receipt this effector received (its own actuation
        evidence), for the receptor to reference. Empty before the first act."""
        return dict(self._last.get("receipt", {}))

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise and invoke NO subprocess."""
        probe = FakeNativeControlRunner({"ok": True, "result": {"ok": True, "entries": []}})
        eff = NativeControlListEffector(probe, allowed_root=".")
        plan = eff.preview(".", ["."])
        try:
            eff.act(plan, allow_receipt=None, content=["."])
            return False
        except RefusedActuation:
            return not probe.calls

    def _within_root(self, target: str) -> bool:
        try:
            Path(target).resolve().relative_to(self._root)
            return True
        except ValueError:
            return False


class NativeControlWriteEffector:
    """Write-class contract for native-control interact verbs (`browser fill`/`type`/
    `click`, `app setvalue`/`invoke`). DEFINED, NOT YET EXERCISED.

    A write-class verb mutates page or app state, so it is irreversible unless the
    effector captures a pre-image and knows how to reverse it. This class states that
    compensation contract without wiring any mutating verb: `act` refuses, and
    `compensate` documents the reversal an exercised implementation must perform
    (re-perceive the pre-image, drive the inverse verb, re-verify). Slice 1 does not
    run it; the surface would escalate it to needs-human anyway (reversible=False)."""

    name = "native-control-write-effector"
    action_kind = "native.write"

    def __init__(self, *, allowed_root: str | Path = ".") -> None:
        self._root = Path(allowed_root).resolve()

    def bound(self) -> dict:
        return {"kind": "native-control", "root": self._root.as_posix()}

    def perceive(self, target: str) -> Observation:
        """A witnessed read of the write target's pre-state. The exercised implementation
        captures this as the pre-image compensation would restore; here it only lets the
        surface run the escalation ladder to needs-human without acting."""
        payload = f"native-write-target:{target}".encode("utf-8")
        return Observation(
            organ=self.name,
            subject=f"native-write://{target}",
            summary="write-class target (unexercised)",
            status=Status.UNVERIFIED,
            provenance=Provenance.witness_bytes(f"native-write://{target}", payload, "low"),
            data={"exists": Path(target).exists(), "sha256": None},
        )

    def preview(self, target: str, content: Any, before: Observation | None = None) -> Plan:
        content_sha = sha256_hex(_canonical(content).encode("utf-8"))
        digest = "sha256:" + sha256_hex(f"{self.action_kind}|{target}|{content_sha}".encode("utf-8"))
        # reversible=False: a write-class verb cannot be undone without an exercised
        # compensation, so the surface escalates it to needs-human by construction.
        return Plan(self.action_kind, target, content_sha, False, False, digest)

    def act(self, plan: Plan, allow_receipt: Any, content: Any) -> Observation:
        raise RefusedActuation(
            "native-control write-class actuation is defined but not yet exercised in this slice"
        )

    def compensate(self, plan: Plan, pre_image: Observation) -> Observation:
        """The reversal an exercised write MUST perform: restore the captured pre-image
        by driving the inverse verb, then re-perceive to confirm. Not yet implemented."""
        raise NotImplementedError(
            "compensation path for native-control writes is a target, not yet exercised"
        )
