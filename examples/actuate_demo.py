"""Accountable actuation — runnable transcript (the demo IS the argument).

The efferent arm: the surface perceives a target, ACTS only on a gate allow,
verifies its own work by re-perceiving, and rolls back a faulty actuation. A
FilesystemEffector bounded to a temp dir — nothing outside it, nothing without an
operator grant. No internet; nothing irreversible.

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/actuate_demo.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from accountable_surface.effector import FilesystemEffector
from accountable_surface.surface import AccountableSurface


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-actuate-demo",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "actuate-demo-agent"},
        "intent": "write the report file",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


class _FaultyEffector(FilesystemEffector):
    """A buggy effector that writes the wrong bytes despite an authorized plan."""

    def _write(self, path, content):
        path.write_bytes(b"CORRUPTED-OUTPUT")


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        surface = AccountableSurface()
        target = str(Path(root) / "report.txt")
        content = b"the frontier, perceived and written natively"

        print(f"== sandbox (the effector's bound): {root}\n")

        print("== ACT without an operator grant ==")
        out = surface.actuate(FilesystemEffector(root), target=target, content=content, authorization={})
        print(f"  acted: {out.acted}   gate: {out.decision.upper()}")
        print(f"  file exists: {Path(target).exists()}   (no grant -> no effect on the world)\n")

        print("== ACT with an operator grant for fs.write ==")
        out = surface.actuate(
            FilesystemEffector(root), target=target, content=content, authorization=_grant(["fs.write"])
        )
        print(f"  acted: {out.acted}   gate: {out.decision.upper()}   verified: {out.verified}")
        print(f"  on disk: {Path(target).read_bytes()!r}")
        print(f"  before -> after digest: {out.before_digest[:23]}... -> {out.after_digest[:23]}...\n")

        print("== ACT with a FAULTY effector (writes wrong bytes) ==")
        Path(target).write_bytes(b"the original, trusted content")
        out = surface.actuate(
            _FaultyEffector(root), target=target, content=content, authorization=_grant(["fs.write"])
        )
        print(f"  acted: {out.acted}   verified: {out.verified}   rolled_back: {out.rolled_back}")
        print(f"  on disk after rollback: {Path(target).read_bytes()!r}")
        print("  (the surface re-perceived, caught its own bad work, and restored the prior state)\n")

        print("== JOURNAL (every actuation, witnessed) ==")
        for entry in surface.journal:
            if entry.kind == "actuation":
                print(f"  [{entry.kind}] {entry.summary}")


if __name__ == "__main__":
    main()
