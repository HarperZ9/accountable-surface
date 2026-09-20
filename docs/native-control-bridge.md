# Native-control bridge -- accountable computer use, first slice

## What this is

The native-control bridge gates one actuator behind the accountable-surface loop.
The actuator is telos native-control, a Node surface that drives a browser (CDP), a
native app (UI Automation), and the OS device layer. On its own, native-control
actuates the moment its CLI runs: it writes its own receipt and a hash-chained
ledger, but nothing decides whether the action should happen. This bridge puts a
native-control verb through the same loop every other accountable-surface effector
uses: witnessed perception, a previewed plan, an operator gate, a bounded act, an
independent re-perception, a verdict, and a durable journal. On top of that it emits
a `project-telos.action-receipt/v1` record, the portable, exportable claim that the
action happened and was checked.

This is the first real end-to-end slice, not the finished surface. It wires exactly
one read-only verb and proves the whole path with tests, live and offline.

## The seam

Two languages, one JSON boundary. Python owns accountability; Node owns actuation.

```
propose (grant)                       Python: AccountableSurface.actuate
  -> perceive target (independent)    Python: os.scandir, witnessed Observation
  -> preview plan                     Python: binds action_kind + target + args hash
  -> gate decision                    Python: proof-surface allow / deny / needs-human
  -> act                              Node:  native-control device ls  (subprocess)
  -> re-perceive + verify             Python: compare actuator listing vs own witness
  -> journal (hash chain)             Python: append-only, tamper-evident
  -> emit action-receipt/v1           Python: the receptor (this slice's new writer)
  -> offline re-derive                anyone: verify_action_receipts.py, stdlib only
```

The bridge lives in accountable-surface, not in telos, because accountable-surface is
the accountability owner. It already holds the gate, the journal, the effector
protocol, the composed certificate, and the offline journal verifier. Adding the
receptor here keeps gate, act, verify, journal, and receipt in one place under one
review. telos stays the pure actuator.

## What is wired and tested (slice 1)

- Verb: `device ls` (list a directory). Read-only, deterministic, and independently
  witnessable. `action_kind = native.device.ls`.
- Effector: `NativeControlListEffector`. Bounded to a directory root. Acts only on a
  gate `allow` for the exact plan, refuses a target outside its root even on an allow,
  and refuses any verb outside the safe read allowlist.
- Runner: `NativeControlRunner` (real subprocess, argv only, no shell) and
  `FakeNativeControlRunner` (offline test double). Both enforce the same allowlist.
- Verify by independent witness: the effector does not trust the actuator's own
  report. It lists the same directory with Python's own `os.scandir` and compares the
  two listings by a size-independent fingerprint (the sorted set of `type:name`). A
  match is a pass; any disagreement is a failure. This closes the gap the
  `CommandEffector` documents, where verify can read only the actor's own account.
- Receptor: `ActionReceiptReceptor` plus `receipt_from_outcome`. Turns an actuation
  outcome into a conformant `project-telos.action-receipt/v1` event and appends it to
  a hash-chained, append-only store.
- Offline verifier: `verify_action_receipts.py`, a zero-dependency CLI. A stranger
  with only the store file re-derives both seals and prints MATCH, DRIFT, or
  UNVERIFIABLE.

Proven live (gate allow -> real `node` subprocess -> independent witness -> MATCH ->
receipt -> offline MATCH -> tamper -> DRIFT) and offline (deterministic, with a fake
runner). See `tests/test_native_control_effector.py`, `tests/test_action_receipt.py`,
and `tests/test_native_control_live.py`.

## The receptor: what it emits and how it is checked

The event follows the read-shaped `happy_path` of the action-receipt contract and
carries the join and verification fields: schema, event type, derived action and event
ids, idempotency key, agent principal, component identity and config hash, action kind
and side-effect class, policy decision, input-material digests, an execution block (a
durable external request id built from the native-control receipt, plus redacted
before and after digests), a verification verdict, a typed result state and stop
reason, and an append-only persistence marker.

Two independent seals, both stdlib-re-derivable:

- Per-event content hash in `receipts[].hash`, computed over every field except itself.
  Editing any field (target, verdict, decision) breaks it.
- Chain hash `_hash = sha256(_prev | canonical(event))`. Deleting or reordering an
  event breaks the linkage. Same construction as the surface journal and
  `verify_journal.py`.

A receipt's integrity is separate from the action's verdict. When the actuator drifts
and the surface catches it, the receipt honestly records `verdict = DRIFT` and its own
chain still re-derives to MATCH. The store is trustworthy about an untrustworthy
action.

### Outcome to receipt mapping

The receptor uses only the contract's typed vocabularies.

| actuation outcome                    | event_type          | result.state | stop_reason                | verdict      |
|--------------------------------------|---------------------|--------------|----------------------------|--------------|
| acted, verified                      | execution_completed | completed    | completed                  | MATCH        |
| acted, verify failed (drift caught)  | execution_failed    | failed       | tool_error                 | DRIFT        |
| refused by effector bound            | execution_failed    | failed       | binding_failed             | UNVERIFIABLE |
| gate deny                            | execution_failed    | cancelled    | policy_denied              | UNVERIFIABLE |
| gate needs-human                     | execution_failed    | cancelled    | verification_unverifiable  | UNVERIFIABLE |

`needs-human` maps to UNVERIFIABLE, never rounded up, matching the surface doctrine.

## Safe subset only

The runner has a hard allowlist, `SAFE_READ_VERBS`. Slice 1 contains exactly
`device ls`. Everything else is refused before a subprocess spawns, in both the real
and fake runners, and the effector refuses to even construct for a verb outside the
allowlist. Refused by construction, with a test asserting it: the mutating device
verbs (`device exec`, `device write`) and the evasion and mass-outreach verbs
(captcha solve, behave stealth, network token minting, gmail send, linkedin post,
scrape targets, mass autofill). None of that code is imported, wired, packaged, or
referenced by the bridge. The bridge touches only the read subset of the actuator.

## Compensation and rollback

A read has no world effect to undo, so `device ls` is reversible by construction and
its rollback is the identity re-perception. It never escalates for irreversibility.

Write-class verbs are different. `NativeControlWriteEffector` states the contract for
them without wiring any mutating verb: it previews as irreversible, so the surface
escalates it to needs-human; its `act` refuses; and its `compensate` documents the
reversal an exercised implementation must perform (capture the pre-image, drive the
inverse verb, re-perceive to confirm). This path is defined and deliberately not yet
exercised. Marked as a target, not a claim.

## What remains a target

- More read verbs: `browser gettext` and `browser snapshot-text` (against an
  operator-launched debug browser), `app tree` and `app value`. Each needs its own
  independent-witness verify before it leaves the target allowlist.
- `device read` is held back. The actuator over-serializes a PowerShell string's
  note-properties, so a small file returns a very large blob through
  `ConvertTo-Json`. The read verb waits on an actuator-side fix in telos.
- Write-class actuation with a live compensation path (the `NativeControlWriteEffector`
  contract, exercised).
- Grant-level bounding of the verb, not only the directory root. The effector's root
  is a path facet the existing `allowed_bounds` machinery already covers by ancestry;
  a verb facet would need a new set facet in `bounds.py`.
- Remote exposure. This bridge is local-loop only. The registry still refuses the
  known effector kinds by name, and no remote path reaches native-control.

## Boundary

This is the capability-gated flagship. The slice is prepared on a branch for review.
It is not a public capability release; that decision is the operator's.
