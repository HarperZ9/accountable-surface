# Accountable Surface

> *Senses and sensibility are what lead to the new frontier. Machines learning to hold themselves accountable.*

A live seam where a model **perceives** and **acts** only through accountability —
witnessed perception, a pre-execution gate, and a tamper-evident, durable memory —
under human stewardship. Composed from existing audited parts:
[coherence-membrane](https://github.com/HarperZ9/coherence-membrane) organs
(witnessed perception) and [proof-surface](https://github.com/HarperZ9/proof-surface)'s
gate (allow / deny / needs-human). It does **not** touch ORCA.

## Why

A parallel agent that drives a browser with Playwright and reads **screenshots**
is guessing at pixels. This surface perceives **structure** — a witnessed,
content-addressed reading with a falsifiable self-test — and gates every action
through an explicit, revocable operator grant. Perception you can audit; action
you can refuse *before* it happens. That is the substrate for safe autonomy: the
danger of "skip every permission" is bounded when every step is witnessed, gated,
and self-checked.

## The loop

```
perceive (afferent)  ->  gate (allow / deny / needs-human)  ->  [act]  ->  witness (journal)
   coherence-membrane            proof-surface                            interocept + JSONL
```

- **Perceive** — organs emit witnessed `Observation`s (provenance digest + a
  falsifiable `selftest`), never screenshots.
- **Gate** — every proposed action is checked against the **operator's** grant by
  proof-surface's pre-execution gate. *The model cannot supply its own authorization.*
- **Witness** — every perception and decision is journaled; `interocept()` is the
  surface's witnessed, content-addressed view of its own conduct, durable across
  sessions (append-only JSONL + replay).

## Doctrine

- Perception is **witnessed**, never a screenshot.
- **Awareness is not authority** — the model perceives freely but cannot authorize its own actions.
- **Accountable over time** — the journal is append-only and replayed; the self-view
  is content-addressed, so the record cannot silently drift.
- Today the surface is **advisory** — it returns the gate's decision and never
  executes. An effector (the efferent arm) is the next phase (see Roadmap).

## Layout

- `src/accountable_surface/surface.py` — `AccountableSurface`: `perceive`, `propose`
  (gated), `interocept` (witnessed self-view), a durable journal. Never executes.
- `src/accountable_surface/server.py` — a FastMCP **live MCP server** exposing
  `perceive`, `propose`, `session_journal`, `interocept`.
- `tests/` — 34 tests. `examples/demo.py` — a runnable transcript;
  `examples/smoke_mcp.py` — a real MCP stdio round-trip.
- `docs/` — design specs (interoception, persistence).

## Install & run

This composes two sibling repos kept off PyPI; put them on the path (or
editable-install them). **coherence-membrane must include `WebDocumentOrgan`**
(branch `feat/web-and-external-organs` or later).

```bash
PP="C:/dev/public/coherence-membrane/src;C:/dev/public/proof-surface/src"

PYTHONPATH="$PP" python -m pytest             # 34 tests (pytest adds ./src)
PYTHONPATH="src;$PP" python examples/demo.py  # runnable transcript
python examples/smoke_mcp.py                  # live MCP round-trip (needs mcp)

# the live MCP server
pip install -e ".[server]"                    # adds mcp
PYTHONPATH="$PP" python -m accountable_surface.server
```

## Wire into an MCP client

```json
{
  "mcpServers": {
    "accountable-surface": {
      "command": "python",
      "args": ["-m", "accountable_surface.server"],
      "env": {
        "PYTHONPATH": "C:/dev/public/accountable-surface/src;C:/dev/public/coherence-membrane/src;C:/dev/public/proof-surface/src",
        "ACCOUNTABLE_SURFACE_GRANTS": "C:/path/to/operator-grants.json",
        "ACCOUNTABLE_SURFACE_JOURNAL": "C:/path/to/session-journal.jsonl"
      }
    }
  }
}
```

### Operator grants (`ACCOUNTABLE_SURFACE_GRANTS`)
A JSON file with one authorization-grant or a list. **The model cannot supply its
own authorization** — only operator-loaded grants gate actions; with none loaded,
the gate is **default-deny**. The grant is the autonomy envelope: its
`scope.allowed_actions` / `allowed_targets` bound what the surface may do.

### Durable memory (`ACCOUNTABLE_SURFACE_JOURNAL`)
A path to an append-only JSONL file. When set, the journal replays on launch and
appends every perception/decision — so the witnessed self-view spans sessions.

## Roadmap

**Built (v0):** witnessed perception · pre-execution gate · interoception ·
durable memory · live MCP server.

**Next — the efferent arm (actuation), accountable by design:** an *effector*
organ that, on a gate `allow`, actually drives the workstation (a browser via
Playwright; the OS) and then **verifies its own work** by re-perceiving the
result against the intended post-condition. Autonomy bounded by the operator
grant — *yolo within an explicit, revocable, witnessed envelope* — with scrutiny
built into every step. Four pillars: **Accountability, Usability, Accessibility,
Efficiency**: perceiving and acting through *structure* (the accessibility tree),
not pixels, is more auditable, more accessible, and cheaper at once.

## License

MIT (c) 2026 Zain Dana Harper
