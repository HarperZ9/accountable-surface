# Spec: Accountable Actuation -- the Efferent Arm (Phase 5, v0)

- **Date:** 2026-06-19
- **Lives in:** `accountable-surface` -- `effector.py` + `AccountableSurface.actuate()`.
- **Full design corpus:** `project-docs/specs/2026-06-19-efferent-arm-actuation.md`.

## Goal

Close the sensorimotor loop. The surface perceives, gates, and remembers; the
efferent arm lets it **act** -- but only through accountability. "Machines holding
themselves accountable" now covers what they *do*, not only what they perceive.

## Doctrine

`propose` stays advisory. `actuate` adds a narrow, gated path from decision to
action:

> The surface may actuate, but **only an effector may act**, **only on a witnessed
> gate `allow`**, **only within the effector's construction-bound**, and **every
> actuation is verified by re-perceiving the effect**.

Awareness is not authority; an allow is not *unchecked* action; action is not
*assumed-done* -- it is verified.

## The loop -- `AccountableSurface.actuate(effector, *, target, content, authorization)`

```
1. before  = effector.perceive(target)                   # witnessed
2. plan    = effector.preview(target, content, before)   # no effect yet
3. outcome = self.propose(plan.action_kind, target, authorization, before)
4. if outcome != allow: journal "not-acted"; STOP. Never act.
5. effector.act(plan, outcome, content)                  # only with the allow receipt
6. after   = effector.perceive(target)                   # re-perceive (proprioception)
7. verdict = effector.verify(plan, after)                # pass / failed
8. if failed and reversible: effector.rollback(plan)
9. journal a witnessed actuation (before/after digests); return ActuationOutcome
```

## The Effector contract

- `perceive(target) -> Observation` -- witnessed state of the target.
- `preview(target, content, before) -> Plan` -- describe the intended action; no effect.
- `act(plan, allow_receipt, content) -> Observation` -- refuses unless the receipt is a
  gate `allow` matching the plan's action+target, the content matches the preview, and
  the target is within the bound. Backs up prior state. Witnesses the result.
- `verify(plan, after) -> Verdict` -- did the on-disk state match the authorized intent?
- `rollback(plan)` -- restore prior state (reversibility).
- `selftest()` -- falsifiable: an act without an allow must raise and write nothing.

`FilesystemEffector` is the first backend (bounded text writes; reversible).
Playwright (DOM / a11y tree) and OS effectors follow under the same contract.

## Proof (tests, offline -- `test_effector.py`, `test_actuate.py`)

- act without an allow → refuses, writes nothing.
- act outside the construction-bound → refuses, even with an allow.
- act with content not matching the preview → refuses.
- no operator grant → `actuate` does not act (default-deny), no effect on the world.
- authorized → acted, verified, journaled.
- a faulty effector (writes wrong bytes) → the surface's re-perception catches it
  (`verified=False`) and rolls back; the prior content is restored.

## Non-goals (v0)

- No browser/OS actuation yet (filesystem first proves the harness safely).
- No multi-step planner / goal-decomposition (single action per call).
- Gate-level plan-digest binding (the effector binds act↔preview; full intent-binding
  at the gate is a refinement).
