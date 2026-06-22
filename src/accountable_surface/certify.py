"""Lift an actuation's already-computed verdicts into one composed Certificate.

The surface already runs the full reconcile (gate -> act -> re-perceive -> verify, with an
optional grounding step). This turns its three verdicts into one proof token:

  gate (proof-surface decision) . effect (re-perceived effector.verify) . grounding
  (reference-cortex confidence)  ->  compose  ->  the action Certificate.

The proven lattice meet does the combining: REFUTED absorbs (a denied gate, a failed effect, or
an ungrounded premise makes the whole action REFUTED), UNVERIFIABLE attenuates (an escalated gate
or a weak premise yields UNVERIFIABLE, never a laundered VERIFIED). TOTAL: an unrecognized verdict
string maps to UNVERIFIABLE and this never raises. Imports only coherence_membrane."""
from __future__ import annotations

from typing import Any

from coherence_membrane.certificate import Certificate, Verdict
from coherence_membrane.composition import compose

_GATE_ORACLE = "proof-surface-gate-v1"
_EFFECT_ORACLE = "accountable-surface-effect-v1"
_GROUND_ORACLE = "reference-cortex-v1"

_GATE = {"allow": Verdict.VERIFIED, "deny": Verdict.REFUTED, "needs-human": Verdict.UNVERIFIABLE}
_EFFECT = {"pass": Verdict.VERIFIED, "failed": Verdict.REFUTED}
_GROUND = {"grounded": Verdict.VERIFIED, "weak": Verdict.UNVERIFIABLE, "ungrounded": Verdict.REFUTED}


def action_certificate(*, decision: str, verdict: str, acted: bool,
                       before_digest: str, after_digest: str | None,
                       grounding: Any = None) -> Certificate:
    """Compose the gate . effect . grounding verdicts into one action Certificate.

    `decision` is the proof-surface gate verdict (allow/deny/needs-human); `verdict` is the
    effector.verify status when `acted` (pass/failed) or the not-acted reason; `grounding`, when
    present, is the reference-cortex Grounding (its `.confidence` and `.digest`)."""
    certs = [Certificate(
        f"gate: {decision}", _GATE.get(decision, Verdict.UNVERIFIABLE), _GATE_ORACLE,
        (("decision", str(decision)),))]
    if acted:
        certs.append(Certificate(
            f"effect: re-perceived {verdict}", _EFFECT.get(verdict, Verdict.UNVERIFIABLE),
            _EFFECT_ORACLE,
            (("verdict", str(verdict)), ("before", str(before_digest)), ("after", str(after_digest or "")))))
    elif verdict == "refused-by-effector":
        certs.append(Certificate(
            "effect: refused by the effector's construction-bound", Verdict.REFUTED, _EFFECT_ORACLE,
            (("verdict", str(verdict)),)))
    if grounding is not None:
        certs.append(Certificate(
            f"grounding: {grounding.confidence}", _GROUND.get(grounding.confidence, Verdict.UNVERIFIABLE),
            _GROUND_ORACLE,
            (("confidence", str(grounding.confidence)), ("digest", str(grounding.digest)))))
    return compose(certs, claim=f"action: decision={decision} verdict={verdict}")
