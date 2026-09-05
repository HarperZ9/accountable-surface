# Changelog

## 2026-09-05 - API Actuation And False-Success Controls

- Added `ApiEffector`: writes through one declared third-party API under the
  effector contract, named by intent rather than by route. The service allowlist
  bounds method, host, and path shape; the gate allow must be bound to the exact
  plan; verification re-reads the resource instead of trusting the response.
- Added `credentials.require_secret` / `has_secret`: a credential is read from the
  environment at call time, refused if it carries a newline, and never reaches a
  Plan, an Observation, the journal, or an error message.
- Added `api_transport.UrllibApiDriver`, a stdlib transport with no policy of its
  own. Honest null: it has no test coverage, because exercising it needs a network
  and a real credential.
- Added `tests/test_false_success.py`: one control per shipped effector, each
  deliberately producing a wrong result a passing verify could accept.
- Added `scope.allowed_bounds`, so a grant can bound an effector's reach and not
  only the action kind.

## 2026-06-29 - Public And Developer Delivery Contract

- Added `AGENTS.md`, `USAGE.md`, `CHANGELOG.md`, and a forward-delivery spec.
- Added GitHub Actions CI with sibling checkouts for `coherence-membrane` and
  `proof-surface`, Python tests, and web JavaScript tests.
- Updated README developer guidance and package URLs.
- Normalized scanner-blocking dash punctuation across public docs, examples,
  tests, source comments, and web strings.

## Current Status

- Runtime: Python 3.10+ package with stdlib-first core and optional MCP server.
- Surfaces: Python API, examples, web demos, MCP server, docs, tests, and CI.
- Verification: pytest suite, Node web tests, public surface sweep.
