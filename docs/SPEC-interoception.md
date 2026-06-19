# Spec: Interoception (Phase 3, v0)

- **Date:** 2026-06-19
- **Roadmap:** Phase 3 (interoception + memory), accountable-surface end-tool.
- **Lives in:** the spike (`scratch/accountable-surface-spike/`), extending `AccountableSurface`.

## Goal

Give the surface a sense of **its own state**. Today it perceives the world
(web) and gates actions; it cannot perceive *itself*. Interoception lets the
surface report a **witnessed, tamper-evident** view of its own session conduct —
what it has perceived, what it proposed, what the gate decided, and what is
pending a human. This is the literal content of "machines holding **themselves**
accountable": the surface's own record flows through the same witness discipline
as everything else.

## Doctrine fit

- **Witnessed, not asserted** — the self-report carries a `journal_digest`
  (SHA-256 of the serialized journal), so the model's account of itself is
  tamper-evident and re-derivable, not a free-text claim.
- **Inert / advisory** — interoception reads the journal and reports; it does not
  mutate it and grants no authority. `Status` is advisory.
- **No new authority** — interoception cannot allow anything; it only reflects.

## Interface — `AccountableSurface.interocept() -> Observation`

- `organ = "interoception"`, `subject = "self://session"`.
- `data`:
  - `perceptions` — count of perception entries.
  - `decisions` — count of decision entries.
  - `decision_counts` — `{allow, deny, needs-human: n}` (present keys only).
  - `pending_needs_human` — count of decisions that escalated to a human.
  - `journal_digest` — `sha256:` + 64-hex of the canonically-serialized journal.
  - `entries` — compact `[{kind, summary}, ...]`.
- `provenance` — `witness_bytes("self://session", <serialized journal>, "high")`.
- Pure read: `interocept()` does **not** append to the journal (no self-reference
  paradox; it witnesses the journal as-is).

Exposed as MCP tool `interocept()` on the live server.

## Proof (tests, offline)

- empty session → `perceptions=0`, `decisions=0`, digest present (64-hex).
- after one `perceive` + an allowed `propose` + a denied `propose` →
  `perceptions=1`, `decisions=2`, `decision_counts={allow:1,deny:1}`,
  `pending_needs_human=0`.
- `journal_digest` changes when the journal changes (re-derivable, tamper-evident).
- provenance digest is full-width; status advisory.
- `interocept()` does not mutate the journal (idempotent read).

## Non-goals (v0)

Durable cross-session episodic memory (JSONL persistence + replay) is the next
increment; v0 is the in-session witnessed self-view. Perceiving the model's
token/context internals is out of scope (not available to this process).
