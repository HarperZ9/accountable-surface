# CLAUDE.md -- Accountable Surface

A live seam where a model perceives and acts only through accountability:
witnessed perception (coherence-membrane) + a pre-execution gate (proof-surface)
+ a tamper-evident, durable journal -- under human stewardship.

## Doctrine (non-negotiable)

- Perception is **witnessed** (provenance digest + a falsifiable selftest), never a screenshot.
- **Awareness is not authority** -- the model never supplies its own authorization;
  only operator-loaded grants gate actions; no grant → default-deny.
- Actuation is **built and gated** (not inert): `propose` is advisory and never
  executes, while `actuate` closes the loop through an effector that acts **only on
  a gate `allow`** for that exact plan, bounded by the operator grant, and **verifies
  its own work** by re-perceiving the result against the intended post-condition.
  Shipped effectors: `FilesystemEffector`, `CommandEffector` (allowlist-only, argv,
  `shell=False`), `WebEffector`, `BrowserEffector`. An irreversible path (e.g. an
  `os.run` that cannot be undone) escalates to `needs-human` unless the operator
  explicitly passes `allow_irreversible`; the effector's construction-bound refuses
  even on a gate `allow` it was not built for. `needs-human` maps to UNVERIFIABLE,
  never rounded up.
- Append-only journal; the self-view is content-addressed and cannot silently drift.

## Boundaries

- No secrets in the repo. Operator grants/journals are paths supplied at runtime,
  never committed.
- This repo does **not** touch released ORCA, and is **not** the quarantined
  semantic-modulation corridor -- keep those separate.

## Dev

- `PYTHONPATH="<cm>/src;<ps>/src" python -m pytest` (pytest adds `./src`) -- 34 tests.
- coherence-membrane must include `WebDocumentOrgan` (branch
  `feat/web-and-external-organs` or later).
- Quality gates: no file > 300 lines, no function > 50 lines, every test asserts
  something meaningful, all tests pass before committing.
