# Changelog

## 2026-09-05 - An Escalation Ladder For Windows Applications

- Added `UiaStructureOrgan` (rung 0): reads a window's control tree through a driver
  and witnesses only what re-derives by name and role. A walk that had to clip the
  tree reads UNVERIFIED, because a partial tree cannot establish that a control is
  absent.
- Added `UiaEffector` (rung 1): invokes or sets one control inside one window, under
  the same effector contract as the other five. The construction bound is the window
  title, the journal records it, and a target naming a second window is refused
  before anything is touched.
- An `invoke` cannot be undone, so the caller declares what should follow it
  (`appears`, `disappears`, `value_is`) and a plan without one is refused at preview
  time. `set_value` is the reversible intent: the prior value is read before the
  write and put back when verification fails.
- Verification re-reads the window. The instrument answers `ok` for an act it
  dispatched, which says nothing about what the application did with it, so its own
  account is never consulted. Two false-success controls hold that line.
- Added `uia_transport.PowerShellUiaDriver`, which refuses the blind keystroke verbs
  `input` and `type` by name before it spawns anything. Honest null: the subprocess
  path has no test coverage; `FakeUiaDriver` drives the whole path offline instead.
- `uia` is refused by name over MCP. It acts on a window belonging to whoever is at
  the machine, and reaching that from off the machine is a separate decision.
- `scope.allowed_bounds` now treats the window facet as a set, so a grant naming
  several windows covers an effector built for any one of them.

## 2026-09-05 - Actuation Over MCP Behind A Capability Registry

- Added the `actuate` MCP tool. A remote caller now closes the whole loop: perceive
  the target, plan, check the operator's gate, act, re-perceive, verify against the
  plan, and roll back a reversible action that did not verify.
- Added `registry.load_effectors`. The operator names a JSON spec file in
  `ACCOUNTABLE_SURFACE_EFFECTORS` and gets exactly the effectors it lists. With the
  variable unset nothing is actuable over MCP, whatever the grants say.
- The spec file refuses `command`, `browser`, and `web` by name, each with the
  reason. `doctor` reports every entry it turned down, so an empty registry never
  leaves a typo looking like a deliberate choice.
- The server reads the registry before the grants, so an action kind the operator
  never exposed causes no grant read and no journal entry.
- A caller's receipt carries the journal entry for its own action and nothing else
  from the journal. A refusal has the same shape as a success, so a caller cannot
  read success out of the structure of the response.
- Honest null: when more than one loaded grant names the action kind, the first one
  runs and the receipt says that it did.

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
