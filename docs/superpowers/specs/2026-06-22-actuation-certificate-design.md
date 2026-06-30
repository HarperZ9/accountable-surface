# Accountable-Surface Actuation → Certificate (Axis B-2) Design

> Date: 2026-06-22 · Status: design (operator-approved: Certificate + grounding wire; ledger deferred) · Home: accountable-surface worktree `feat/actuation-certificate`.

## 0 · Goal

Unify the **richest action organism** onto the shared proof token: every `AccountableSurface`
actuation emits a composed **`coherence_membrane.Certificate`** -- `gate ∘ effect ∘ grounding` --
carried in `ActuationOutcome` and the journal, the way `workstation` (Axis B-1) was wired. The
action's verdict becomes the proven lattice *meet* of its steps, re-checkable and composable,
instead of a parallel string vocabulary.

## 1 · The insight

`AccountableSurface.actuate` **already runs the full reconcile**: `perceive → gate (proof-surface
decide) → act-on-allow → re-perceive (after) → verify (effector.verify) [→ rollback]`, with an
optional grounding step. It witnesses the result as `ActuationOutcome` strings + a `JournalEntry`.
This increment **lifts its existing gate, effect, and grounding verdicts into one `Certificate`**
-- no new control flow, no new actuation, purely a witness upgrade.

## 2 · The mapping (the three already-computed verdicts → the lattice)

| Step | Source | → Verdict |
|---|---|---|
| **gate** | the proof-surface decision (`ActionOutcome.decision`) | `allow`→VERIFIED, `deny`→REFUTED, `needs-human`→UNVERIFIABLE |
| **effect** | `effector.verify(...).status` (re-perceived) | `pass`→VERIFIED, `failed`→REFUTED |
| **grounding** | `Grounding.confidence` | `grounded`→VERIFIED, `weak`→UNVERIFIABLE, `ungrounded`→REFUTED |

`needs-human`→UNVERIFIABLE and `weak`→UNVERIFIABLE are the sound mappings: under `compose`,
UNVERIFIABLE **attenuates** (an escalated gate or a weak premise yields an UNVERIFIABLE action, not
a VERIFIED one), and REFUTED **absorbs** (a denied gate, a failed effect, or an ungrounded premise
makes the whole action REFUTED -- a theorem, not a convention).

## 3 · The pieces

### 3.1 `src/accountable_surface/certify.py` (new, < 50 lines)

```python
action_certificate(*, decision: str, verdict: str, acted: bool,
                   before_digest: str, after_digest: str | None,
                   grounding=None) -> Certificate
```
Builds the applicable step certs and returns `compose([...])`:
- **gate cert** (always): `Certificate(f"gate: {decision}", _GATE[decision], "proof-surface-gate-v1",
  (("decision", decision),))`.
- **effect cert**: when `acted`, from `verdict` (`pass`/`failed`), oracle
  `accountable-surface-effect-v1`, evidence `(("verdict", verdict), ("before", before_digest),
  ("after", after_digest or ""))`. When **not** acted but `verdict == "refused-by-effector"`, a
  REFUTED effect cert ("refused by the effector's construction-bound" -- a gate `allow` the effector
  still refused).
- **grounding cert**: when `grounding is not None`, from `grounding.confidence`, oracle
  `reference-cortex-v1`, evidence `(("confidence", …), ("digest", grounding.digest))`.
- `compose(certs, claim=f"action: decision={decision} verdict={verdict}")` → oracle `composed-v1`.

The map dicts default to UNVERIFIABLE for any unrecognized string (TOTAL; never raises).

### 3.2 `src/accountable_surface/surface.py` (modify, minimal -- keep it off the 300-line gate)

- `ActuationOutcome` gains `certificate: dict = field(default_factory=dict)` (additive, last field;
  the composed cert's `to_dict()` -- round-trippable via the keystone).
- `_record_actuation` computes `cert = action_certificate(decision=decision, verdict=verdict,
  acted=acted, before_digest=before.provenance.digest, after_digest=(after.provenance.digest if
  after is not None else None), grounding=grounding)`, sets it on the returned `ActuationOutcome`,
  and adds `"certificate": cert.to_dict()` to the `JournalEntry` detail. The witness becomes the
  verdict.

No other control flow changes. `surface.py` is already 431 lines (over this repo's 300-line gate);
the new verdict logic lives in `certify.py`, not in it. (The `surface.py` split is a separate,
out-of-scope cleanup.)

## 4 · Path-by-path verdict (verifying the mapping is sound on every branch)

| actuate branch | decision | verdict | acted | grounding | composed action verdict |
|---|---|---|---|---|---|
| gate deny | deny | not-acted | F | none | **REFUTED** (gate) |
| gate needs-human | needs-human | not-acted | F | none | **UNVERIFIABLE** (gate) |
| ungrounded premise | needs-human | ungrounded-premise | F | ungrounded | **REFUTED** (grounding absorbs) |
| irreversible escalation | needs-human | irreversible-needs-human | F | grounded/weak/none | **UNVERIFIABLE** (gate; grounding ≥ UNVERIFIABLE) |
| refused by effector | allow | refused-by-effector | F | maybe | **REFUTED** (refusal effect absorbs) |
| acted + verified | allow | pass | T | grounded | **VERIFIED** |
| acted + verified, weak premise | allow | pass | T | weak | **UNVERIFIABLE** (weak attenuates) |
| acted + failed (rolled back) | allow | failed | T | any | **REFUTED** (effect absorbs) |

Every branch yields the honest meet. No path can launder a blocked/failed action into VERIFIED.

## 5 · Tests

1. **`tests/test_certify.py`** (new) -- `action_certificate` for each row of §4: assert the composed
   `verdict` and that the evidence carries the step oracles. Plus: TOTAL (an unrecognized decision/
   verdict string → UNVERIFIABLE, never raises); grounding omitted → only gate(+effect) compose.
2. **`tests/test_actuate.py`** (extend) -- assert a real `surface.actuate(...)` over the fs effector
   returns an `ActuationOutcome` whose `certificate["verdict"]` matches the outcome (e.g. a verified
   write → `"verified"`, a denied action → `"refuted"`), and that the journal entry carries the
   certificate. Reuse the existing fixtures.

## 6 · Success criteria

- Every `ActuationOutcome` carries a composed action `Certificate` whose verdict is the proven meet
  of gate ∘ effect ∘ grounding; a denied/failed/ungrounded/refused action is never VERIFIED.
- The journal entry carries the certificate (the witness IS the verdict).
- **All 129 pre-existing tests pass** (additive; no control-flow change). `certify.py` < 50 lines;
  `surface.py` grows only by the field + the call.
- `certify.py` imports only `coherence_membrane` (Certificate/Verdict/compose); no new deps.

## 7 · Deferred (later wires, from the architecture map)

- **Ledger bridge** (record fs actuations to the cdev ledger, Axis B-1 style) -- needs the target/
  action_kind on `ActuationOutcome`.
- **Journal → MemoryStore** (wire 4, the structural break) -- now unblocked by `Certificate.from_dict`.
- **Effector `Protocol`** + the `surface.py` 300-line split.
