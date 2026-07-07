# Introduction to Accountable Surface

## What it is

Accountable Surface is a Python workbench that lets an AI agent act on real
targets, files, web pages, and OS commands, under explicit operator control.
Every action follows the same loop: perceive the target as structure, propose
a plan, pass an operator-loaded gate, act through a bounded effector, verify
the result by re-perceiving, and record the whole exchange in a durable
journal. The core is stdlib only: no browser binary, no HTTP library, no
framework. It composes two sibling packages, coherence-membrane (perception)
and proof-surface (the gate).

What you get in practice:

- Four effectors: filesystem (bounded, reversible, self-verifying), native web
  (navigate, fill by label, submit, no browser needed), JS-capable browser
  (optional Playwright backend), and OS commands (allowlist only, no shell).
- A grounding cortex that scores reference relevance and says "ungrounded"
  instead of guessing, with native arXiv lookup.
- Bounded autonomy: a multi-step plan under one grant, halting on the first
  denial or failed verification.
- A live MCP server, a shared world server you can watch in a browser, and an
  append-only journal that replays across sessions.

## Why it exists

Agent frameworks make it easy to grant an agent broad authority and hope for
the best. This surface takes the opposite bet: the agent perceives freely but
never authorizes its own actions. The operator's grant is the envelope, the
gate is default-deny, and every step leaves a record you can replay and
re-check. Autonomy stays useful because it stays reviewable.

## Core concepts

**Observation.** Perception returns a content-addressed structural reading of
the target (a sha256 digest plus a falsifiable self-test), not a screenshot.
The same target re-perceived should produce the same digest; that is what
makes verification possible.

**Grant.** A plain JSON object supplied by the operator: who granted it, to
which agent, for which actions and targets, valid for what window. The model
cannot fabricate one. No grant loaded means the gate denies everything.

**Gate.** Every proposed action is checked by proof-surface's pre-execution
gate. Three outcomes: allow, deny, needs-human. Irreversible actions (a POST,
an OS command that cannot be undone) escalate to needs-human unless the
operator explicitly passes `allow_irreversible`.

**Effector.** The only thing that touches the world. Each effector is bounded
by construction (a filesystem root, an origin list, a command allowlist) and
refuses work outside its bound even on a gate allow.

**Verification and rollback.** After acting, the surface re-perceives the
target and compares it to the intended post-condition. A reversible action
that fails verification is rolled back. Nothing is assumed done.

**Journal and interoception.** Every perception, decision, and actuation is
appended to a journal. `interocept()` returns a content-addressed view of the
surface's own conduct, so the record cannot drift silently. Point
`ACCOUNTABLE_SURFACE_JOURNAL` at a JSONL file and it persists across sessions.

**Grounding.** An action may carry a justification. The reference cortex
scores it against witnessed references; an ungrounded premise escalates to
needs-human, and the references ride along on the outcome as the action's
citation.

## First ten minutes

Clone the three repos side by side and install:

```powershell
git clone https://github.com/HarperZ9/accountable-surface.git
git clone https://github.com/HarperZ9/coherence-membrane.git
git clone https://github.com/HarperZ9/proof-surface.git
cd accountable-surface
$env:PYTHONPATH = "src;..\coherence-membrane\src;..\proof-surface\src"
python -m pip install -e ".[test]"
```

Run the basic loop:

```powershell
python examples/demo.py
```

You will see a witnessed perception (title, links, digest), a gate ALLOW for
an action inside the grant, a gate DENY for one outside it, and the journal.

Run the full actuation loop:

```powershell
python examples/actuate_demo.py
```

Three acts against a temp-dir sandbox: no grant (denied, no file created), a
valid grant (written and verified, before and after digests printed), and a
deliberately faulty effector (caught at verification and rolled back).

Confirm the suite passes:

```powershell
python -m pytest
```

Expect 223 tests passing in a few seconds.

Then pick the transcript closest to your use case:

- `examples/web_actuate_demo.py`: native web actuation against a real
  localhost server, no browser.
- `examples/spa_actuate_demo.py`: the JS-capable browser path, offline via the
  fake driver.
- `examples/goal_demo.py`: a multi-step plan under one grant.
- `examples/grounding_demo.py` and `examples/grounded_actuate_demo.py`: the
  reference cortex, including an action that must cite grounded references.
- `examples/smoke_mcp.py`: a real MCP stdio round-trip (install the `[server]`
  extra first).

To watch the surface act live, start the shared world server and open the
printed URL:

```powershell
python -m accountable_surface.world.server 8808
```

## Where to go next

- [USAGE.md](../USAGE.md): operational guide, including the optional
  Playwright browser backend and the MCP client configuration.
- [SPEC-actuation.md](SPEC-actuation.md), [SPEC-interoception.md](SPEC-interoception.md),
  [SPEC-persistence.md](SPEC-persistence.md): the design specs behind the loop.
- [README](../README.md): the full feature list and worked example.
- Peer repos: [coherence-membrane](https://github.com/HarperZ9/coherence-membrane)
  and [proof-surface](https://github.com/HarperZ9/proof-surface).

The tool is alpha (0.1.0). The loop and the gate semantics are stable in
intent; names and signatures may still move between 0.x releases.
