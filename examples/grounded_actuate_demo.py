"""Grounded actuation — runnable transcript: an action must cite grounded references.

Same authorized write, two premises: a GROUNDED one proceeds and cites its evidence;
an UNGROUNDED one escalates to needs-human and never touches the world. Evidence is
gated like authority. Offline (FakeSource cortex, temp dir).

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/grounded_actuate_demo.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from accountable_surface.effector import FilesystemEffector
from accountable_surface.reference import FakeSource, ReferenceCortex
from accountable_surface.surface import AccountableSurface


def _grant(actions):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-gad",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "gad"},
        "intent": "write a config, grounded in evidence",
        "scope": {"allowed_actions": list(actions), "allowed_targets": []},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


CORTEX = ReferenceCortex(FakeSource([
    {"source": "arxiv", "ref_id": "2401.0011",
     "title": "safe bounded file writes for autonomous agents",
     "summary": "reversible, verified writes", "url": "http://arxiv.org/abs/2401.0011"},
]))


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        eff = FilesystemEffector(root)
        target = str(Path(root) / "config.txt")
        grant = _grant(["fs.write"])

        print("== ACT with a GROUNDED premise: 'safe bounded file writes' ==")
        surface = AccountableSurface()
        out = surface.actuate(eff, target=target, content=b"ok", authorization=grant,
                              justification="safe bounded file writes", cortex=CORTEX)
        print(f"  acted: {out.acted}  verified: {out.verified}  premise: {out.grounding.confidence}")
        for ref in out.grounding.references:
            print(f"    cites: [{ref.relevance}] {ref.title}  ({ref.source}:{ref.ref_id})")
        print(f"  on disk: {Path(target).read_bytes()!r}\n")

        if Path(target).exists():
            Path(target).unlink()

        print("== ACT with an UNGROUNDED premise: 'medieval falconry techniques' ==")
        surface2 = AccountableSurface()
        out = surface2.actuate(eff, target=target, content=b"ok", authorization=grant,
                               justification="medieval falconry techniques", cortex=CORTEX)
        print(f"  acted: {out.acted}  decision: {out.decision}  verdict: {out.verdict}")
        print(f"  file exists: {Path(target).exists()}   (the ungrounded action never ran)\n")

        print("== JOURNAL (second attempt — grounding + actuation, witnessed) ==")
        for entry in surface2.journal:
            if entry.kind in ("grounding", "actuation"):
                print(f"  [{entry.kind}] {entry.summary}")


if __name__ == "__main__":
    main()
