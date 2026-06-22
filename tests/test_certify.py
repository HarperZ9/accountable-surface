"""Axis B-2: the composed action Certificate (gate ∘ effect ∘ grounding)."""
from __future__ import annotations

from types import SimpleNamespace

from coherence_membrane.certificate import Verdict
from accountable_surface.certify import action_certificate


def _g(confidence):
    return SimpleNamespace(confidence=confidence, digest="sha256:" + "a" * 64)


def test_gate_deny_is_refuted():
    c = action_certificate(decision="deny", verdict="not-acted", acted=False,
                           before_digest="b", after_digest=None)
    assert c.verdict is Verdict.REFUTED


def test_gate_needs_human_is_unverifiable():
    c = action_certificate(decision="needs-human", verdict="not-acted", acted=False,
                           before_digest="b", after_digest=None)
    assert c.verdict is Verdict.UNVERIFIABLE


def test_acted_verified_grounded_is_verified():
    c = action_certificate(decision="allow", verdict="pass", acted=True,
                           before_digest="b", after_digest="a", grounding=_g("grounded"))
    assert c.verdict is Verdict.VERIFIED


def test_acted_verified_weak_grounding_attenuates():
    c = action_certificate(decision="allow", verdict="pass", acted=True,
                           before_digest="b", after_digest="a", grounding=_g("weak"))
    assert c.verdict is Verdict.UNVERIFIABLE          # weak premise attenuates a verified effect


def test_acted_failed_is_refuted():
    c = action_certificate(decision="allow", verdict="failed", acted=True,
                           before_digest="b", after_digest="a")
    assert c.verdict is Verdict.REFUTED


def test_ungrounded_premise_is_refuted():
    c = action_certificate(decision="needs-human", verdict="ungrounded-premise", acted=False,
                           before_digest="b", after_digest=None, grounding=_g("ungrounded"))
    assert c.verdict is Verdict.REFUTED


def test_refused_by_effector_is_refuted():
    c = action_certificate(decision="allow", verdict="refused-by-effector", acted=False,
                           before_digest="b", after_digest=None)
    assert c.verdict is Verdict.REFUTED              # gate allowed, effector's bound refused


def test_irreversible_escalation_is_unverifiable():
    # needs-human gate + a grounded premise: the escalation (not the grounding) governs
    c = action_certificate(decision="needs-human", verdict="irreversible-needs-human", acted=False,
                           before_digest="b", after_digest=None, grounding=_g("grounded"))
    assert c.verdict is Verdict.UNVERIFIABLE         # UNVERIFIABLE gate meets VERIFIED grounding


def test_evidence_carries_step_oracles():
    c = action_certificate(decision="allow", verdict="pass", acted=True,
                           before_digest="b", after_digest="a", grounding=_g("grounded"))
    oracles = " ".join(k for k, _ in c.evidence)
    assert "proof-surface-gate-v1" in oracles
    assert "accountable-surface-effect-v1" in oracles
    assert "reference-cortex-v1" in oracles


def test_total_on_unrecognized_strings():
    c = action_certificate(decision="??", verdict="??", acted=True, before_digest="b", after_digest="a")
    assert c.verdict is Verdict.UNVERIFIABLE          # never raises; off-lattice -> UNVERIFIABLE
