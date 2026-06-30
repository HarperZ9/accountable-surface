# The Shared World -- a live, embodied, accountable operating surface

> "Giving an AI a body, in a world the operator co-inhabits." The model perceives real material,
> acts on it through its own native hands, and every move is gated then witnessed with a
> re-checkable receipt -- watched live, together.

**Goal:** Assemble the body's existing organs into ONE live loop on **real material**: a model
perceives a real artifact, proposes an action, the action crosses an accountability gate, is
actuated by native fs/os hands (dogfooded -- not Playwright), re-perceived, and witnessed with a
composed Certificate -- streamed live to a browser "world" the operator co-inhabits and steers.

**Architecture:** A zero-dep `ThreadingHTTPServer` + Server-Sent-Events surface (the proven
studio-engine `server.py` pattern) driving the real, public `AccountableSurface` loop. We compose
the body, we don't reinvent it. The Shared Frame's `render.js` + `verdict.js` (dual-aperture render
+ client-side certificate re-check) become the embedded "shared seeing" room.

**Home:** `c:/dev/public/accountable-surface` (the body's own public repo). New subsystem
`src/accountable_surface/world/` + `web/`. Branch `feat/shared-world`.

**Tech stack:** Python stdlib only (`http.server`, `json`, `dataclasses`) + the sibling organs
(`accountable_surface`, `coherence_membrane`). Browser: vanilla ES modules, SSE. No third-party deps.

## What we compose (real, mapped APIs -- not imagined)

- `AccountableSurface(journal_path)` -- the body. `.perceive(subject) -> Observation`,
  `.actuate(effector, *, target, content, authorization, justification=None, cortex=None)
  -> ActuationOutcome`, `.pursue(goal, steps, *, authorization) -> GoalOutcome`, `.journal`.
- `ActuationOutcome` fields: `acted, decision, verified, verdict, rolled_back, reasons,
  before_digest, after_digest, grounding, certificate (dict)`.
- Hands: `FilesystemEffector(allowed_root)` (fs.write; reversible w/ rollback),
  `CommandEffector(runner, allowed_commands, cwd)` (os.run; argv-only, no shell).
- Gate: operator **grant** dict (`scope.allowed_actions`, `scope.allowed_targets`, principal,
  expiry) → default-deny `decide()`; verdicts `allow | deny | needs-human`.
- Grounding: `ReferenceCortex(source).ground(subject) -> Grounding`; ungrounded → `needs-human`.
- Receipt: `action_certificate(...)` → composed Certificate (gate ∧ effect ∧ grounding meet),
  already on every `ActuationOutcome`.

## Honest scope (the thesis is proof-before-trust; the surface must not overclaim)

- The hands are **fs/os** -- real files and bounded argv processes. **Full GUI motor control**
  (cursor/clicks/typing into apps, live screen capture) is **frontier, not shipped**; the surface
  states this plainly and shows the real hands it has.
- The "AI" driving the loop is **model-agnostic**: the surface runs whatever actions are proposed
  (by a real model via API, or authored live in-session) through the body. We do not fake a model;
  the proposed action + its justification are explicit inputs, and every consequence is witnessed.
- Material lives in a **sandbox `WORLD_ROOT`** the FilesystemEffector is bounded to. Nothing
  outside the granted scope is touchable. Grants and journal paths are operator-supplied at runtime.

## File structure

```
src/accountable_surface/world/
  __init__.py
  session.py     # WorldSession -- the testable core: wraps the body + bound hands + grant;
                 #   .act(proposed) -> WorldStep (one witnessed loop turn); .snapshot() -> world state
  server.py      # zero-dep ThreadingHTTPServer + SSE: GET /world, POST /act, GET /world/stream,
                 #   static web/ serving
web/
  index.html     # the shared world: material · the model's perception · proposed action ·
                 #   gate decision · actuation · the re-checkable receipt -- portfolio-skinned
  world.js       # SSE client + the loop view; drives showCertificate/recheck
  render.js      # (reused from the Shared Frame) dual-aperture renderer
  verdict.js     # (reused) client-side Certificate re-check
tests/
  test_world_session.py   # TDD: granted action acts+verifies+receipt-verified; denied -> refuted;
                          #   snapshot reflects dir + journal; os.run path
docs/design/2026-06-22-shared-world-surface.md   # this
```

## Increments (each independently testable; commit per green step)

### A -- The body's live driver (the spine)
- `WorldSession`: bind an `AccountableSurface` + `FilesystemEffector(WORLD_ROOT)` (+ optional
  `CommandEffector`) + an operator grant. `act(proposed)` runs one proposed action through the real
  loop and returns a `WorldStep` (perception before, proposed, gate decision, acted/verified/verdict,
  before/after digest, **certificate dict**, material-after). `snapshot()` returns the world state
  (the WORLD_ROOT listing + focused file + the witnessed journal + grant summary).
- TDD (`test_world_session.py`): a granted `fs.write` → `acted and verified`, certificate verdict
  `verified`, material reflects the write; an out-of-grant target → gate `deny`, `not acted`,
  certificate `refuted`; `snapshot()` reflects the dir + journal; an `os.run` granted command path.
- **Verify:** pytest green; the loop genuinely acts on real files under the sandbox root.

### B -- The shared world (browser)
- `server.py`: GET `/world` (snapshot), POST `/act` (proposed → WorldStep), GET `/world/stream`
  (SSE of steps), static `web/`. `web/index.html` + `world.js`: the live view -- material, the
  model's witnessed perception, the proposed action, the gate decision (with reasons), the
  actuation (before/after digests), and the receipt (reuse `verdict.js` recheck -- re-derive the
  verdict in the browser). Portfolio skin; the Shared Frame as the "shared seeing" room.
- **Verify:** Playwright -- submit an action, watch the world update live; re-check reproduces the
  certificate; a denied action shows the gate refusing.

### C -- Talking + the operator participating
- A narration channel (the model's reasoning per step: what it perceives, why it acts) and operator
  participation: approve a `needs-human` step, or steer/propose the next action -- real-time dialogue
  about the material. The "between the two of us" beat.
- **Verify:** Playwright -- a needs-human action waits for the operator; approval lets it proceed,
  witnessed.

### D -- Dogfood a real task + honest framing
- Drive a real end-to-end task: the body perceives a real file, proposes an edit, gate allows, acts,
  witnesses, hands the operator a receipt -- using its own hands, not Playwright. The universality
  framing (doctor/animator/researcher/ordinary person) as honest copy. Accessibility + polish.
- **Verify:** Playwright across the full loop; `node --check`; the journal is a re-checkable record.

## Out of scope / deferred (named, not silently dropped)

- Full GUI motor control (cursor/keyboard into arbitrary apps) + live continuous screen perception --
  the next limb; the surface is honest that it isn't shipped.
- A real model API wired as the autonomous driver -- the loop is model-agnostic; wiring a specific
  model is a later step.
- The public portfolio page -- comes after the live system is real (operator's choice: system first).
