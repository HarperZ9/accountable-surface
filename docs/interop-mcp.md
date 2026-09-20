# Accountable actuation over MCP -- the interoperable server

One stdio MCP server puts a computer-use action through accountability: the model
perceives with a witness, the action is gated before it runs, the effector reaches
only as far as the grant allows, the surface re-perceives and verifies the effect
against its own eyes, and the whole thing lands in a tamper-evident journal and an
action receipt a stranger can re-derive offline. Other harnesses adopt it as one
server: Claude Code, Codex, Cursor, and the Flywheel bundled lane.

Read-only `device ls` is wired and proven end to end today. Write-class actuation and
broad browser / app / device breadth are target, not shipped, and this document says
which is which.

## Run it now

```
python -m accountable_surface.interop_mcp        # stdio JSON-RPC MCP server
# or, once installed:
accountable-surface-mcp
```

The protocol layer is stdlib-only JSON-RPC over stdio -- no FastMCP, nothing to pip
install for a harness to spawn it and list tools. `initialize`, `tools/list`,
`status`, and `doctor` answer even where the action runtime is absent; the action
tools load it lazily (the sibling repos coherence-membrane and proof-surface) and
return a named error otherwise.

Offline demonstration with a fake actuator (no Node, deterministic):

```
python examples/interop_mcp_demo.py
```

Adoption snippets for each harness are in `interop/README.md`; the machine-readable
manifests are `interop/claude-code.mcp.json`, `interop/mcp-server.json`, and
`interop/flywheel-lane.json`.

## The tools, and the six primitives

| Primitive | Tool | What it does |
| --- | --- | --- |
| perceive | `accountable-surface.perceive` | Witness a subject (a directory by independent `os.scandir`, or a web page / file) as an Observation with a provenance digest. No gate, no act. |
| propose / gate | `accountable-surface.propose` | Run the pre-execution gate for a proposed action against the operator's grants. Returns the advisory decision allow / deny / needs-human. Never acts. |
| actuate | `accountable-surface.actuate` | The full loop for a wired safe verb: perceive, plan, gate, act, re-perceive, verify, journal, emit a receipt. Only `native.device.ls` is wired. |
| (read-only verb) | `accountable-surface.device_ls` | Convenience over `actuate` for the shipped verb: list a directory through the loop. |
| journal | `accountable-surface.journal` | Return this session's journal with a re-derived chain-integrity verdict. |
| receipt | `accountable-surface.receipt` | Re-derive the action-receipt store offline: MATCH / DRIFT / UNVERIFIABLE, with the store path. |

`gate` is the decision `propose` returns, not a separate call; `actuate` re-runs the
gate itself before acting. `status` and `doctor` are network-free health tools.

## What this adds over ungated computer use (evidence-bound)

| Property | Ungated computer use | This server | Evidence |
| --- | --- | --- | --- |
| Authorization | The tool acts when called | Reach-bounded operator grant; default-deny; the model cannot self-authorize | `tests/test_interop_mcp.py::test_device_ls_default_deny_reaches_no_actuator` |
| Reach bound | Unbounded | Effector construction bound plus the grant's `allowed_bounds`, covered by path ancestry | `tests/test_native_control_effector.py::test_target_outside_bound_refused` |
| Verification | The actor's own report, or none | Independent self-verify: the surface re-lists with its own `os.scandir` and compares; a wrong or lying listing fails verify (false-success control) | `tests/test_interop_mcp.py::test_drifting_actuator_is_caught_and_receipt_records_drift` |
| Rollback | None | A reversible act that fails verify is rolled back; a read is reversible by construction; write-class rollback is defined, not exercised | `tests/test_native_control_effector.py::test_actuator_underreport_is_caught_and_rolled_back` |
| Audit | Ephemeral logs | Append-only, hash-chained journal plus an `action-receipt/v1` event, both re-derivable offline with stdlib only | `verify_journal.py`, `verify_action_receipts.py`, `tests/test_interop_mcp.py::test_receipt_rederives_then_drifts_on_tamper` |
| Excluded by construction | Nothing | CAPTCHA solving, anti-bot stealth / fingerprint patching, reCAPTCHA token harvest, mass or obfuscated authenticated outreach, mutating device verbs -- unreachable through any tool | `tests/test_interop_exclusions.py` |

The verdict vocabulary is honest about a bad action: when the actuator drifts and the
surface catches it, the receipt records `DRIFT` and its own chain still re-derives to
`MATCH`. The store is trustworthy about an untrustworthy action.

## Hard exclusions

The boundary is the `SAFE_READ_VERBS` allowlist in `native_control_effector.py`: the
server reaches exactly the verbs it names (today, `device ls`). `EXCLUDED_CAPABILITIES`
in `interop_mcp.py` restates, in five named classes, what must never be reachable:

- `captcha_solving` -- CAPTCHA / reCAPTCHA solving
- `anti_bot_stealth` -- stealth, behavior spoofing, fingerprint patching
- `token_harvest` -- reCAPTCHA or bot-detection token harvest
- `mass_outreach` -- mass or obfuscated authenticated sends, posts, scraping, mass autofill
- `mutating_device` -- `device exec`, `device write`

No tool advertises them, `resolve_wired_action` refuses them before an effector is
built or a subprocess spawns, and the actuator runner refuses them too. There is no
argument a caller can pass through any tool to reach one. `tests/test_interop_exclusions.py`
asserts each of these independently.

## Shippable now vs target

Shippable now:

- The stdio MCP server and its six primitives plus `device_ls`, `status`, `doctor`.
- The read-only `native.device.ls` verb, gated, bounded, independently verified,
  journaled, and receipted, proven offline (fake actuator) and live (real Node
  subprocess -- see `tests/test_native_control_live.py`).
- The interop manifests and the offline receipt verifier.

Target, not shipped (stated so no reader mistakes it for a claim):

- Write-class actuation with a live compensation path. `NativeControlWriteEffector`
  states the contract and refuses; the surface escalates a write to needs-human by
  construction.
- Broader read verbs (`browser gettext`, `browser snapshot-text`, `app tree`,
  `app value`, `device read`), each pending its own independent-witness verify.
- Grant-level bounding of the verb, not only the directory root.

## Remote / streamable-HTTP (Muse)

stdio is what ships. A remote effector surface (Muse) would carry the same primitives
over MCP streamable-HTTP rather than stdio. The controls that path needs already exist
in this repo and are not re-implemented for the local loop: durable authority
(finite-use reservations, durable revocation, idempotency) in
`accountable_surface.authority_state`, scoped read authority for the precondition,
verify, and rollback phases in `accountable_surface.read_authority`, and protected-path
refusal in `accountable_surface.protected_paths`. The action-capable FastMCP server in
`accountable_surface.server` (the `[server]` extra) is the remote host for that path.
The interop stdio server here is deliberately local-loop only: the registry still
refuses the known effector kinds by name, and no remote path reaches native-control.
