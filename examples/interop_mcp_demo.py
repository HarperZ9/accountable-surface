"""Interop MCP server -- runnable transcript (the demo IS the argument).

Drives the accountable-actuation runtime the interop MCP server carries, offline and
deterministic: a FakeNativeControlRunner stands in for the Node actuator, so the whole
loop -- gate, act, independent verify, journal, receipt -- runs with nothing to spawn.
It lists a temp directory through the shipped read-only verb `device ls`, shows the
gate default-denying without a grant, catches a drifting actuator, and re-derives the
action-receipt store offline. No internet; nothing irreversible.

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/interop_mcp_demo.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from accountable_surface.interop_runtime import AccountableInterop
from accountable_surface.native_control_effector import FakeNativeControlRunner


def _grant(actions):
    return {
        "authorization_version": "0.1", "receipt_id": "rcpt-interop-demo",
        "kind": "authorization-grant", "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "interop-demo-agent"}, "intent": "list the working directory",
        "scope": {"allowed_actions": list(actions), "allowed_targets": []},
        "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _receipt(entries, ok=True):
    return {"schema": "project-telos.native-control/v1", "action": "device.ls", "ok": ok,
            "result": {"ok": ok, "entries": entries, "count": len(entries)}, "at": "2026-09-19T00:00:00Z"}


def _entries(path):
    return [{"name": e.name, "type": "dir" if e.is_dir() else "file"} for e in os.scandir(path)]


def _show(label, payload):
    print(f"\n== {label} ==")
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        (work / "report.md").write_text("hello", encoding="utf-8")
        (work / "data").mkdir()
        receipts = str(Path(tmp) / "receipts.jsonl")
        clock = lambda: "2026-09-19T00:00:00+00:00"  # noqa: E731 - a fixed clock for a byte-stable demo.

        # 1) No grant: the gate default-denies and no actuator is reached.
        ungranted = AccountableInterop(
            grants=[], receipt_path=receipts, clock=clock,
            runner_factory=lambda d, v: FakeNativeControlRunner(_receipt(_entries(work))))
        _show("device_ls with NO grant (default-deny)", ungranted.device_ls(str(work)))

        # 2) With a grant naming native.device.ls: acted, independently verified, receipted.
        honest = FakeNativeControlRunner(_receipt(_entries(work)))
        interop = AccountableInterop(
            grants=[_grant(["native.device.ls"])], receipt_path=receipts, clock=clock,
            runner_factory=lambda d, v: honest)
        _show("device_ls under a grant (act + verify + receipt)", interop.device_ls(str(work)))
        _show("receipt store re-derived offline", interop.receipt())

        # 3) A drifting actuator under-reports a real entry -- the independent witness catches it.
        understated = [e for e in _entries(work) if e["name"] != "report.md"]
        drifting = AccountableInterop(
            grants=[_grant(["native.device.ls"])], receipt_path=str(Path(tmp) / "drift.jsonl"),
            clock=clock, runner_factory=lambda d, v: FakeNativeControlRunner(_receipt(understated)))
        _show("device_ls with a DRIFTING actuator (caught + rolled back)", drifting.device_ls(str(work)))


if __name__ == "__main__":
    main()
