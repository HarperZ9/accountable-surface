"""Tests for grounded actuation -- an action must cite grounded references.

Offline. When a justification + reference cortex are supplied, the surface grounds
the action's premise before acting: an ungrounded premise escalates to needs-human
and nothing happens; a grounded one proceeds and the references ride along on the
outcome (the action's citation). Without a justification, behaviour is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from accountable_surface.effector import FilesystemEffector
from accountable_surface.reference import FakeSource, ReferenceCortex
from accountable_surface.surface import AccountableSurface


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-grounded-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "grounded-agent"},
        "intent": "grounded actuation test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _cortex():
    return ReferenceCortex(FakeSource([
        {"source": "arxiv", "ref_id": "2401.1", "title": "safe file writes in language agents",
         "summary": "bounded, verified, reversible writes", "url": "http://x/1"},
    ]))


def test_grounded_premise_allows_the_action_and_cites_references(tmp_path):
    surface = AccountableSurface()
    target = str(tmp_path / "f.txt")
    out = surface.actuate(
        FilesystemEffector(tmp_path), target=target, content=b"hi",
        authorization=_grant(["fs.write"]), justification="safe file writes", cortex=_cortex(),
    )
    assert out.acted is True
    assert out.verified is True
    assert out.grounding is not None
    assert out.grounding.confidence in ("grounded", "weak")
    assert len(out.grounding.references) >= 1  # the action cites its evidence
    assert any(e.kind == "grounding" for e in surface.journal)


def test_ungrounded_premise_escalates_and_does_not_act(tmp_path):
    surface = AccountableSurface()
    target = str(tmp_path / "f.txt")
    out = surface.actuate(
        FilesystemEffector(tmp_path), target=target, content=b"hi",
        authorization=_grant(["fs.write"]), justification="orbital mechanics of comets", cortex=_cortex(),
    )
    assert out.acted is False
    assert out.decision == "needs-human"
    assert out.verdict == "ungrounded-premise"
    assert not Path(target).exists()  # an ungrounded action does NOT touch the world


def test_no_justification_skips_the_grounding_gate(tmp_path):
    surface = AccountableSurface()
    target = str(tmp_path / "f.txt")
    out = surface.actuate(
        FilesystemEffector(tmp_path), target=target, content=b"hi", authorization=_grant(["fs.write"]),
    )
    assert out.acted is True
    assert out.grounding is None  # backward compatible: no cortex, no grounding gate
