# Spec: Durable Memory (Phase 3)

- **Date:** 2026-06-19
- **Roadmap:** Phase 3 (durable memory), accountable-surface end-tool.
- **Lives in:** the spike (`scratch/accountable-surface-spike/`), extending `AccountableSurface`.
- **Builds on:** [SPEC-interoception.md](SPEC-interoception.md) — the named "next
  increment" (durable cross-session JSONL persistence + replay).

## Goal

Make the surface's journal — its record of every perception and every gate
decision — **survive across sessions**. Interoception (v0) gave the surface a
witnessed view of its *own* conduct, but only in-session: the record died with
the process. Durable memory persists the journal to an **append-only JSONL**
file and **replays** it on launch, so the witnessed self-view spans sessions.
This is the substrate for machines holding themselves accountable *over time*,
not merely within a single run.

## Doctrine fit

- **Append-only** — the surface only ever appends to the journal file; it never
  rewrites or truncates. The record grows monotonically, like a witness log.
- **Tamper-evident, not tamper-proof** — a line that does not parse on replay is
  **counted** (`replay_errors`), never silently dropped. Corruption/tampering is
  surfaced, not hidden.
- **Content-addressed self-view** — the interoception `journal_digest` is over
  journal *content*, not storage. The same activity yields the same digest
  whether created in-session or replayed, so persistence cannot silently alter
  what the surface attests to.
- **Opt-in, operator-supplied** — like authorization grants, the journal path is
  supplied out-of-band by the operator (`ACCOUNTABLE_SURFACE_JOURNAL`), never by
  the model. No path → in-memory only (unchanged prior behavior).
- **Additive / inert** — a new optional parameter; it touches no other component
  and does not touch ORCA.

## Interface

### `AccountableSurface(journal_path: str | Path | None = None)`
- `None` (default) → in-memory journal only; no disk I/O. Backward compatible.
- A path → on construction, **replay** any existing journal into memory; every
  subsequent `perceive` / `propose` **appends** its entry to the file.
- `replay_errors: int` — count of unparseable lines encountered on replay.

### Persistence format
One compact JSON object per line (JSONL), canonical key order:
`{"detail": {...}, "kind": "...", "summary": "..."}`. Round-trips via
`JournalEntry.to_dict()` / `JournalEntry.from_dict()`.

### Server (`ACCOUNTABLE_SURFACE_JOURNAL`)
`load_journal_path()` resolves the path from the env var (or an explicit arg);
the live MCP server constructs its surface with it. Unset → in-memory.
`session_journal()` returns the full journal, including replayed prior-session
entries.

## Proof (tests, offline — `test_persistence.py`, `test_server.py`)

- `perceive` / `propose` each append exactly one JSONL line.
- replay on init restores the prior journal (count, kinds, order).
- round-trip fidelity: a replayed entry equals the original (kind, summary, detail).
- append-only: a second session replays then appends; the file holds both, in order.
- a malformed line is counted in `replay_errors`; valid entries still load.
- interoception spans replayed sessions (counts prior-session history).
- the interoception digest is storage-independent (replayed == in-memory for the same activity).
- no path → no disk written (pure in-memory).
- server: `load_journal_path` from arg / env / None; an end-to-end persist+replay through the impl layer.

## Non-goals (this increment)

- **Compaction / rotation** — the log grows unbounded; rotation is a later concern.
- **Cryptographic chaining** — entries are individually witnessed via the
  interoception digest, but the file is not yet a hash-chained ledger (each line
  committing to the prior). That is the natural hardening step toward a
  tamper-*proof* (not just tamper-*evident*) record.
- **Concurrent writers** — one surface per journal file; no file locking.
