"""Runtime layer for the interop MCP server -- it admits the accountable-actuation
core and carries the six primitives (perceive, propose/gate, actuate, journal,
receipt) plus the one shipped read-only verb, device ls.

interop_mcp.py owns the stdlib-only stdio JSON-RPC framing and imports this module
LAZILY, so identity and health answer even where this runtime (the surface plus its
sibling repos coherence-membrane and proof-surface) is not installed.

SAFE SUBSET ONLY. ``WIRED_ACTIONS`` is derived from ``SAFE_READ_VERBS``, so the
server reaches exactly the verbs the effector allows -- today ``native.device.ls``.
``resolve_wired_action`` refuses anything else, and it double-checks the pair against
both the safe allowlist and the interop ``EXCLUDED_VERBS`` denylist before returning,
so an excluded capability cannot be reached through any tool no matter the argument.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from coherence_membrane.observation import sha256_hex

from accountable_surface.action_receipt import (
    ActionReceiptReceptor,
    canonical,
    receipt_from_outcome,
    verify_receipts,
)
from accountable_surface.authority_store import load_operator_grants
from accountable_surface.effector import RefusedActuation
from accountable_surface.grant import action_authorization
from accountable_surface.interop_mcp import EXCLUDED_CAPABILITIES, EXCLUDED_VERBS
from accountable_surface.native_control_effector import (
    SAFE_READ_VERBS,
    FakeNativeControlRunner,
    NativeControlListEffector,
    NativeControlRunner,
)
from accountable_surface.surface import AccountableSurface

# The action kinds the server will actuate, derived from the effector's safe allowlist
# so the two can never drift apart. action_kind == f"native.{domain}.{verb}".
WIRED_ACTIONS: dict[str, tuple[str, str]] = {
    f"native.{domain}.{verb}": (domain, verb) for (domain, verb) in SAFE_READ_VERBS
}


def resolve_wired_action(action_kind: str) -> tuple[str, str]:
    """Map an action_kind onto its (domain, verb), or refuse. Refuses anything not
    wired, anything the safe allowlist does not contain, and anything on the interop
    exclusion denylist -- three independent checks, all fail-closed."""
    if action_kind not in WIRED_ACTIONS:
        raise RefusedActuation(
            f"action_kind {action_kind!r} is not wired; exposed: {sorted(WIRED_ACTIONS)}"
        )
    domain, verb = WIRED_ACTIONS[action_kind]
    if (domain, verb) not in SAFE_READ_VERBS:
        raise RefusedActuation(f"{domain}.{verb} is not in the safe read allowlist")
    if (domain, verb) in EXCLUDED_VERBS:
        raise RefusedActuation(f"{domain}.{verb} is a hard-excluded capability")
    return domain, verb


def is_excluded(domain: str, verb: str) -> bool:
    return (domain, verb) in EXCLUDED_VERBS


def _excluded_report() -> dict[str, list[str]]:
    return {cls: [f"{d}.{v}" for d, v in pairs] for cls, pairs in EXCLUDED_CAPABILITIES.items()}


def _journal_path_from_env() -> Path | None:
    value = os.environ.get("ACCOUNTABLE_SURFACE_JOURNAL")
    return Path(value) if value else None


def _receipt_path_from_env(journal_path: Path | None) -> Path:
    value = os.environ.get("ACCOUNTABLE_SURFACE_RECEIPTS")
    if value:
        return Path(value)
    if journal_path is not None:
        return Path(str(journal_path) + ".receipts.jsonl")
    return Path(tempfile.gettempdir()) / f"accountable-surface-receipts-{os.getpid()}.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountableInterop:
    """The runtime behind the interop MCP tools. Holds one surface, one operator-grant
    set, one native-control runner factory, and one append-only action-receipt store.
    The model never supplies authorization; grants are loaded out-of-band by the
    operator (``ACCOUNTABLE_SURFACE_GRANTS``), never over the wire."""

    def __init__(
        self,
        *,
        surface: AccountableSurface | None = None,
        grants: list[dict] | None = None,
        runner_factory: Callable[[str, str], Any] | None = None,
        receipt_path: str | Path | None = None,
        journal_path: str | Path | None = None,
        native_control_script: str | None = None,
        node: str = "node",
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._journal_path = Path(journal_path) if journal_path else _journal_path_from_env()
        self._surface = surface or AccountableSurface(journal_path=self._journal_path)
        self._grants = list(grants) if grants is not None else load_operator_grants()
        self._script = (native_control_script if native_control_script is not None
                        else os.environ.get("ACCOUNTABLE_SURFACE_NATIVE_CONTROL_SCRIPT"))
        self._node = node
        self._runner_factory = runner_factory or self._default_runner_factory
        self._receipt_path = Path(receipt_path) if receipt_path else _receipt_path_from_env(self._journal_path)
        self._clock = clock or _utc_now
        self._receptor = ActionReceiptReceptor(self._receipt_path)

    # --- perception (pure read, no gate) -------------------------------------

    def perceive(self, subject: str) -> dict:
        """Witness a subject: a directory (the surface's own os.scandir witness) or a
        web page / file. No gate, no actuation."""
        path = Path(subject)
        if path.is_dir():
            witness = NativeControlListEffector(
                FakeNativeControlRunner({"ok": True, "result": {"ok": True, "entries": []}}),
                allowed_root=path,
            )
            return witness.perceive(str(path)).to_dict()
        return self._surface.perceive(subject).to_dict()

    # --- the gate (advisory, never acts) -------------------------------------

    def propose(self, action_kind: str, target: str, expected_digest: str | None = None) -> dict:
        """Run the pre-execution gate against the operator's grants. Allow iff a grant
        permits it; else needs-human if any escalates; else deny. Default-deny with no
        grant. The surface never executes -- this returns the advisory decision only."""
        if not self._grants:
            return {"decision": "deny", "gate": "deny", "checks": {"authorization": "fail"},
                    "reasons": ["no operator grant is loaded -- default-deny; the model cannot self-authorize"]}
        outcomes = [
            self._surface.propose(action_kind=action_kind, target=target,
                                  authorization=action_authorization(grant), expected_digest=expected_digest)
            for grant in self._grants
        ]
        chosen = (next((o for o in outcomes if o.decision == "allow"), None)
                  or next((o for o in outcomes if o.decision == "needs-human"), None)
                  or outcomes[0])
        return {"decision": chosen.decision, "gate": chosen.decision,
                "reasons": list(chosen.reasons), "checks": dict(chosen.checks)}

    # --- actuation (the full loop, safe verbs only) --------------------------

    def actuate(self, action_kind: str, target: str, content: Any = None,
                expected_digest: str | None = None, idempotency_key: str | None = None) -> dict:
        """Run perceive -> plan -> gate -> act -> re-perceive -> verify -> journal, then
        emit an action-receipt/v1. Only wired SAFE verbs are reachable; anything else is
        refused before an effector is built or a subprocess spawns."""
        try:
            domain, verb = resolve_wired_action(action_kind)
        except RefusedActuation as exc:
            return self._refused(str(exc), exposed_action_kinds=sorted(WIRED_ACTIONS),
                                 excluded_capabilities=_excluded_report())
        try:
            runner = self._runner_factory(domain, verb)
        except RefusedActuation as exc:
            return self._refused(str(exc))
        params = list(content) if isinstance(content, (list, tuple)) else [target]
        effector = NativeControlListEffector(runner, allowed_root=target, domain=domain, verb=verb)
        grant = self._grant_for(action_kind)
        since = len(self._surface.journal)
        outcome = self._surface.actuate(effector, target=target, content=params,
                                        authorization=grant or {}, expected_digest=expected_digest)
        receipt = self._emit_receipt(outcome, action_kind, target, params, effector, idempotency_key)
        notes = [] if grant else [f"no operator grant names {action_kind!r} -- default-deny"]
        return self._outcome_dict(outcome, since, receipt, notes)

    def device_ls(self, path: str) -> dict:
        """The shipped read-only verb: list a directory through the accountable loop."""
        return self.actuate("native.device.ls", path, content=[path])

    # --- session reads -------------------------------------------------------

    def journal(self) -> dict:
        verdict = self._surface.verify_journal()
        return {"chain_ok": verdict["chain_ok"], "tamper_count": verdict["tamper_count"],
                "replay_errors": verdict.get("replay_errors", 0),
                "entries": [entry.to_dict() for entry in self._surface.journal]}

    def receipt(self, include_events: bool = False) -> dict:
        """Re-derive the action-receipt store offline: MATCH / DRIFT / UNVERIFIABLE."""
        path = self._receipt_path
        if not path.exists():
            return {"label": "UNVERIFIABLE", "detail": "no receipts emitted yet",
                    "count": 0, "storage_path": str(path)}
        text = path.read_text(encoding="utf-8")
        label, detail = verify_receipts(text)
        lines = [line for line in text.splitlines() if line.strip()]
        result: dict[str, Any] = {"label": label, "detail": detail, "count": len(lines),
                                  "storage_path": str(path)}
        if include_events:
            import json

            result["events"] = [json.loads(line) for line in lines]
        return result

    def doctor_runtime(self) -> dict:
        return {
            "available": True,
            "grants_loaded": len(self._grants),
            "journal_persistent": getattr(self._surface, "_journal_path", None) is not None,
            "receipt_store": str(self._receipt_path),
            "native_control_script_configured": bool(self._script),
            "node": self._node,
            "wired_action_kinds": sorted(WIRED_ACTIONS),
            "safe_read_verbs": [f"{d}.{v}" for d, v in sorted(SAFE_READ_VERBS)],
            "excluded_capabilities": _excluded_report(),
        }

    # --- internals -----------------------------------------------------------

    def _default_runner_factory(self, domain: str, verb: str) -> Any:
        if not self._script:
            raise RefusedActuation(
                "native-control actuator not configured (set ACCOUNTABLE_SURFACE_NATIVE_CONTROL_SCRIPT); "
                "the accountability loop will not run without an actuator to gate"
            )
        return NativeControlRunner(self._script, node=self._node)

    def _grant_for(self, action_kind: str) -> dict | None:
        for grant in self._grants:
            if action_kind in ((grant.get("scope") or {}).get("allowed_actions") or []):
                return grant
        return None

    def _emit_receipt(self, outcome: Any, action_kind: str, target: str, params: list,
                      effector: Any, idempotency_key: str | None) -> dict:
        args_hash = "sha256:" + sha256_hex(canonical(list(params)).encode("utf-8"))
        created_at = self._clock()
        idem = idempotency_key or sha256_hex(
            f"{action_kind}|{target}|{args_hash}|{created_at}".encode("utf-8")
        )[:24]
        try:
            nc = effector.native_control_receipt()
        except Exception:  # noqa: BLE001 - a missing actuator receipt is not fatal.
            nc = {}
        event = receipt_from_outcome(
            outcome, action_kind=action_kind, target=target, args_hash=args_hash,
            native_control_receipt=nc or None, idempotency_key=idem, created_at=created_at,
            side_effect_class="read", reversible=True,
        )
        persistence = self._receptor.emit(event)
        return {**persistence, "verdict": event["verification"]["verdict"],
                "storage_path": str(self._receipt_path)}

    def _outcome_dict(self, outcome: Any, since: int, receipt: dict, notes: list[str]) -> dict:
        mine = [entry.to_dict() for entry in self._surface.journal[since:] if entry.kind == "actuation"]
        return {
            "decision": outcome.decision, "acted": outcome.acted, "verified": outcome.verified,
            "verdict": outcome.verdict, "rolled_back": outcome.rolled_back,
            "reasons": list(outcome.reasons) + notes,
            "before_digest": outcome.before_digest, "after_digest": outcome.after_digest,
            "certificate": outcome.certificate,
            "journal_entry": mine[-1] if mine else None,
            "receipt": receipt,
        }

    @staticmethod
    def _refused(reason: str, **extra: Any) -> dict:
        payload: dict[str, Any] = {
            "decision": "deny", "acted": False, "verified": False,
            "verdict": "refused-before-actuation", "rolled_back": False,
            "reasons": [reason], "certificate": {}, "journal_entry": None, "receipt": None,
        }
        payload.update(extra)
        return payload


_DEFAULT: AccountableInterop | None = None


def default_interop() -> AccountableInterop:
    """The process-wide interop runtime, built from the environment on first use."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = AccountableInterop()
    return _DEFAULT
