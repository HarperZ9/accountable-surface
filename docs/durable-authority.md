# Durable authority state

Durable authority is optional local state for the MCP actuation path. It uses the
Python stdlib `sqlite3` module only. If SQLite is unavailable, locked past the
configured busy timeout, corrupt, or on an unsupported path, remote mutation fails
closed; there is no custom fallback ledger.

Set `ACCOUNTABLE_SURFACE_AUTHORITY_STATE` beside the existing grant and journal
paths:

```powershell
$env:ACCOUNTABLE_SURFACE_GRANTS = "C:/ops/accountable/grants.json"
$env:ACCOUNTABLE_SURFACE_JOURNAL = "C:/ops/accountable/session-journal.jsonl"
$env:ACCOUNTABLE_SURFACE_AUTHORITY_STATE = "C:/ops/accountable/authority-state.sqlite3"
```

When this variable is set, remote `actuate` requires an explicit
`idempotency_key`. The key is hashed before storage. Reusing the same key with
the same stable request fingerprint does not authorize a second action; reusing
it with a different target, content, grant reference, selected read scope, or
other fingerprinted input is refused as an idempotency conflict.

Finite usage limits are read from `max_actions` or `scope.max_actions`. A slot is
reserved before the target is read and committed immediately before the effector
acts. Reserved, committed, successful, failed, and ambiguous operations count
against availability. A reservation that expires before `commit_to_act` is still
unresolved and still counts until the operator records recovery; expiry reports
`authority-reservation-recovery-required` and never silently frees a slot.

Revocation can be recorded in the authority DB, so a stale grant file restored to
`revoked: false` still denies under the same grant reference. The grant reference
is stable across harmless JSON reserialization and includes the authorization
version, receipt id, principal id, agent id, and nonce when present. Grant digests
remain in state records for exact source pairing.

The remote filesystem path also refuses targets that overlap configured grant,
authority-state, and journal files, including SQLite `-wal` and `-shm` sidecars,
resolvable aliases, and existing hardlinks where the platform can prove file
identity. Indeterminate identity lookup errors deny. This is a local custody
boundary, not a race-proof or rollback-proof authority service: an actor able to
rewrite the protected state and all anchors can still roll it back or truncate it
without detection unless an external protected anchor is added.

Operator-only recovery commands are local CLI commands, not MCP tools:

```powershell
accountable-surface-authority revoke --state C:/ops/accountable/authority-state.sqlite3 --grant C:/ops/accountable/grant.json --reason "operator revoked"
accountable-surface-authority recover-precommit --state C:/ops/accountable/authority-state.sqlite3 --reservation-id <id> --reason "operator verified no commit_to_act record"
accountable-surface-authority mark-ambiguous --state C:/ops/accountable/authority-state.sqlite3 --reservation-id <id> --reason "operator could not prove final effect"
accountable-surface-authority doctor --state C:/ops/accountable/authority-state.sqlite3
```

The CLI reports redacted grant references, reservation ids, status, and digests.
It does not return grant bodies, prior payloads, target contents, credentials, or
journal entries.

This state layer prevents tested local MCP double-spends and idempotent replays.
It does not prove spoken or semantic alignment, mid-effector interruption,
adversary-proof tamper resistance, rollback detection without a protected anchor,
or safety for browser, UIA, command, provider, or network effectors.
