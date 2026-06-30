# Spec: Accountable Surface Forward Delivery Contract

## Objective

Bring Accountable Surface to the shared Project Telos public/developer delivery
floor while preserving its witnessed perception, grant-gated action, journal,
MCP, and web-demo behavior.

## Requirements

- [x] Add root `AGENTS.md`, `USAGE.md`, `CHANGELOG.md`, and implementation
  receipt.
- [x] Add CI that checks out required sibling repositories and runs Python and
  web tests.
- [x] Keep README and package metadata clear for public users and developers.
- [x] Normalize scanner-blocking punctuation without changing behavior.
- [x] Preserve the grant boundary: operator-loaded grants authorize; models do
  not authorize themselves.

## Technical Approach

Use documentation, CI, metadata, and text-normalization changes. Existing tests
remain the behavioral authority for action, verification, refusal, journals,
reference grounding, world sessions, and web rechecks.

## Success Criteria

- [x] `python -m pytest` passes with sibling repository paths on `PYTHONPATH`.
- [x] `node --test web/*.test.mjs` passes.
- [x] `python -m public_surface_sweeper . --workspace --json` reports `MATCH`.
- [x] `git diff --check` exits 0.

## Status: IMPLEMENTED
