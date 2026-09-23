# Changelog

## 0.3.1 - 2026-09-22

- Declares the runtime dependencies. The wheel previously installed cleanly and
  then raised `ModuleNotFoundError` on first import, because `coherence-membrane`
  and `proof-surface` were omitted while neither was published. Both are on PyPI
  now, so both are declared. `mcp` stays optional under `[server]`.
- Adds an OIDC trusted-publishing release workflow with tag/version, artifact
  digest, clean-venv entry-point resolution, and sdist-rebuild gates.
- Aligns the declared version with the repository's tag history. `pyproject.toml`
  and `accountable_surface.__version__` both read `0.1.0` through the v0.1.0,
  v0.2.1 and v0.3.0 tags, so the MCP `serverInfo` reported `0.1.0` to every
  client regardless of which release was running. A new guard binds the two.

## Unreleased

- Interoperable MCP server for the accountable-actuation core
  (`accountable_surface.interop_mcp` + `interop_runtime`). A zero-third-party-dependency
  JSON-RPC-over-stdio server (stdlib framing, no FastMCP) so other harnesses -- Claude
  Code, Codex, Cursor, and the Flywheel bundled lane -- adopt one seam. Exposes the six
  accountable primitives (`perceive`, `propose`/gate, `actuate`, `journal`, `receipt`)
  plus the shipped read-only verb `device_ls`, and `status`/`doctor`. Console script
  `accountable-surface-mcp`. Identity and health answer even where the runtime is not
  installed; the action tools import it lazily and return a named error otherwise.
- Interop manifests under `interop/`: a Claude Code `.mcp.json` server entry, a generic
  MCP server descriptor, a Flywheel lane entry, and an "add this to your harness" README
  for Codex and Cursor. Concise overview and an evidence-bound comparison over ungated
  computer use in `docs/interop-mcp.md`.
- Hard exclusions are enforced at the server boundary and asserted by test
  (`tests/test_interop_exclusions.py`): CAPTCHA solving, anti-bot stealth / fingerprint
  patching, reCAPTCHA token harvest, and mass or obfuscated authenticated outreach are
  unreachable through any tool. The `SAFE_READ_VERBS` allowlist stays the boundary;
  `EXCLUDED_CAPABILITIES` is the explicit second assertion of it. Shippable today: the
  read-only `device ls` slice. Target, not shipped: write-class actuation and broad
  browser / app / device breadth.
- Not a public capability release; prepared on a branch for review.

- Native-control bridge (first accountable-computer-use slice, capability-gated).
  Gates one telos native-control verb, `device ls`, through the full loop: perceive,
  preview, gate, act via a Node subprocess, re-perceive, verify, journal. New
  modules `native_control_effector.py` (`NativeControlListEffector`,
  `NativeControlRunner`, `FakeNativeControlRunner`, and a write-class contract stub
  `NativeControlWriteEffector`) and `action_receipt.py` (`ActionReceiptReceptor`,
  `receipt_from_outcome`, `verify_receipts`), the first runtime writer of a
  `project-telos.action-receipt/v1` event.
- Independent-witness verify: the effector checks the actuator's directory listing
  against the surface's own `os.scandir`, so a wrong or lying listing fails verify
  (false-success control) rather than passing on the actor's own account.
- Offline receipt verifier `verify_action_receipts.py` (zero-dependency, stdlib
  only): a receipt store re-derives to MATCH; any edited, deleted, or reordered
  receipt yields DRIFT.
- Safe subset only. The runner refuses any verb outside a read allowlist by
  construction; the evasion and mass-outreach verbs and the mutating device verbs
  are unreachable through the bridge, asserted by test. See
  `docs/native-control-bridge.md` for the wired-vs-target status and the write-class
  compensation contract (defined, not yet exercised).
- Not a public capability release; prepared on a branch for review.

## 0.2.0 - 2026-09-18

- Added optional SQLite authority state for remote MCP actuation: durable
  revocation, atomic finite-use reservations, idempotency, and local recovery
  commands. Unresolved reservations remain unavailable until operator recovery.
- With durable authority enabled, protected grant, journal, and state paths are
  refused before access, including resolvable aliases and existing hardlinks.
  This does not provide race-proof path access or rollback detection without an
  external protected anchor. See `docs/durable-authority.md` for configuration
  and the tested boundaries.
- Bug fix: remote `perceive`, `session_journal`, and `actuate` now require
  explicit scoped read grants. Remote writes fail closed unless their required
  before/backup/after/rollback read phases match a known filesystem or API
  target contract, and grants are reloaded just before mutation.
- Bug fix: `actuate(expected_digest=...)` now refuses before effect when the
  supplied precondition cannot be bound to an explicit observation identity, and
  filesystem/API/browser preconditions reach the gate as state checks instead of
  silently becoming `not-applicable`.
- Limit: this does not harden filesystem TOCTOU/symlink races, interrupt
  revocation mid-method, or gate local `surface.actuate()` reads.

## 2026-09-13 - First Release Recovery

- Refreshed the README verification block from the old `3e4b342` checkpoint to
  current public `main` at `a0bafe6`.
- Added the first-release checklist in `docs/RELEASE.md`: it records the exact
  test, build, Twine, and proof-install commands for a GitHub source release and
  optional package-registry upload.
- Publication remains a separate reviewed action. This update prepares evidence
  and documentation; it does not create a tag, GitHub release, PyPI project, or
  registry upload.

## 2026-09-05 - The Escalator That Records Why It Fell

- Added `escalator.py`: rungs are climbed in cost order and each fall is recorded with
  the reason that justified paying for the next one. `Ascent.trace()` prints the whole
  climb, one line per rung.
- A question travels the ladder, not a plan. Each probe restates it in its own nouns or
  declines, which keeps the rungs from acquiring a shared verb vocabulary they do not
  have.
- A rung that fell never sets the answer. When the ladder runs out the ascent is
  NEEDS_HUMAN, carries `rederivable = "none"`, and hands over the perception from the
  deepest rung that produced one.
- Added `StructureProbe` (rung 0) and `PixelProbe` (rung 3). A whole control tree
  settles absence as a result; a clipped one falls instead. Pixels never resolve a
  label, and the decline is the probe's honest outcome.
- Rungs 1 and 2 carry no probe. An escalator that acted to find something out would be
  an actuation no grant authorized, and a test asserts a full climb sends nothing but
  read verbs.
- Added a false-success control for the ladder: a rung-3 sight with a content digest, a
  perceptual hash, and a coarse description reads like an answer and settles nothing.

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
