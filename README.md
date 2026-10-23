<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/HarperZ9/accountable-surface/main/docs/art/hero-dark.svg">
  <img src="https://raw.githubusercontent.com/HarperZ9/accountable-surface/main/docs/art/hero-light.svg" alt="accountable-surface: Lets an AI agent take only the actions a person has approved. Lines arrive from one side at a toothed ring around a bright core; most pass through and a few stop at the ring with a short cross mark." width="100%">
</picture>

# accountable-surface

Lets an AI agent take only the actions a person has approved.

[![PyPI: 0.3.1](https://img.shields.io/badge/pypi-0.3.1-e6e1d6?style=flat-square&labelColor=1a1712)](https://pypi.org/project/accountable-surface/)
[![CI](https://github.com/HarperZ9/accountable-surface/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/accountable-surface/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-FSL--1.1--MIT-e6e1d6?style=flat-square&labelColor=1a1712)](https://github.com/HarperZ9/accountable-surface/blob/main/LICENSE)
![python 3.10+](https://img.shields.io/badge/python-3.10%2B-e6e1d6?style=flat-square&labelColor=1a1712)

accountable-surface is a Python library and MCP server that sits between an AI agent and the things it can change. The agent asks to write a file, call an API, submit a web form or press a button in a Windows app. The request runs only if a permission grant you wrote covers it. After the action, the library reads the target again to confirm the change landed. An action that fails that check is undone where it can be. Every decision and outcome goes into a hash-chained log that a standalone script can check.

It is for developers wiring an agent to real files, services or desktop apps who want a deny-by-default permission check and a result check in code they can test. The package and its two required packages use only the Python standard library.

## Quickstart

```
pip install accountable-surface
```

Save this as `quickstart.py` and run it with `python quickstart.py`:

```python
import tempfile
from pathlib import Path
from accountable_surface import AccountableSurface, FilesystemEffector

sandbox = Path(tempfile.mkdtemp())
grant = {
    "authorization_version": "0.1",
    "receipt_id": "grant-1",
    "kind": "authorization-grant",
    "principal": {"id": "alice", "role": "owner"},
    "agent": {"id": "my-agent"},
    "intent": "write the report file",
    "scope": {"allowed_actions": ["fs.write"], "allowed_targets": []},
    "granted_at": "2026-01-01T00:00:00+00:00",
    "expires_at": "2030-01-01T00:00:00+00:00",
    "revoked": False,
}

surface = AccountableSurface(journal_path=sandbox / "journal.jsonl")
effector = FilesystemEffector(str(sandbox))
target = str(sandbox / "report.txt")

denied = surface.actuate(effector, target=target, content=b"hello", authorization={})
print(denied.acted, denied.decision)

allowed = surface.actuate(effector, target=target, content=b"hello", authorization=grant)
print(allowed.acted, allowed.decision, allowed.verified)
print(sandbox / "journal.jsonl")
```

Output:

```
False deny
True allow True
```

The third line it prints is the path of `journal.jsonl` in a new temporary folder.

With no grant the write is refused and no file is created. With the grant it runs, and `verified` is `True` because the file was read back and matched. To check the log, run `verify_journal.py` from a clone of this repository on the printed path. It prints `MATCH  chain intact over 4 entries`. Change one byte of the log and it prints `DRIFT` and exits 1.

For a demo that also shows a faulty write being caught and rolled back, clone the repository and run `python examples/actuate_demo.py` with `src` on `PYTHONPATH`.

## What it can do

Each kind of action has its own effector, built with a fixed reach (a root folder, an origin, one API service, one window):

- **Files.** `FilesystemEffector` writes inside one root, reads the result back, and rolls back a write that fails the check.
- **Commands.** `CommandEffector` runs allowlisted programs as argv with `shell=False`. Every command counts as irreversible, so it stops for a person unless allowed.
- **Web forms without a browser.** `WebEffector` fills fields by their visible label and submits forms on server-rendered pages, using only the standard library. It stays on one origin.
- **Browser pages.** `BrowserEffector` clicks by accessible label on JavaScript pages. Install `accountable-surface[browser]` to drive it with Playwright; tests use a built-in fake driver.
- **Third-party APIs.** `ApiEffector` calls one declared service through named operations. The agent supplies the intent and body; the host, route and credential stay in the effector, and the credential is read from an environment variable at call time.
- **Windows apps.** `UiaEffector` presses a button or sets a field by its accessible name in one window, then reads the window again to check the result. A fake driver runs the same path on any OS.
- **Logs.** The journal is append-only JSONL. Each entry is chained to the previous one, so an edited, deleted or reordered entry is detected on reload and by `verify_journal.py`.
- **MCP.** `accountable-surface-server` (install `accountable-surface[server]`) exposes `perceive`, `propose`, `actuate`, `session_journal`, `interocept`, `status` and `doctor`. Remote `actuate` reaches only the effectors you list in a registry file, and only filesystem and API effectors can be listed.

Limits that apply to the list above:

- Alpha. The API may change between 0.x releases. One maintainer.
- A grant with no `scope.allowed_bounds` says nothing about reach. The effector's own construction bound is then the only limit.
- Rollback runs when a reversible action fails its check: file writes, browser navigation and form fills, and API operations that declare an undo call. Commands, page scripts, Windows app clicks and API calls with no undo are irreversible. They stop for a person unless allowed, and a failed check on one is reported, not reversed.
- The second, dependency-free MCP server (`accountable-surface-mcp`) wires one action today: a read-only directory listing that needs the separate Node native-control tool. Its other tools inspect, gate and check logs.
- The shared world server and its web UI run from a source checkout only; the `web/` files are not in the wheel.
- Changes on `main` after 0.3.1 are not on PyPI yet: irreversible actions need the grant to list them in `scope.allowed_irreversible_actions`, and the world server requires a per-run token and refuses cross-origin requests. In 0.3.1 the caller flag `allow_irreversible=True` alone is enough.

## How it compares

- **Claude Code permissions and hooks, Codex approval modes.** These ask a person or match a rule before a tool runs, inside one agent client. accountable-surface is a library you call from your own code or any MCP client. It also checks the result after the action and keeps a log you can verify offline.
- **LangGraph human-in-the-loop interrupts.** LangGraph pauses a graph so a person can approve a step. accountable-surface decides from a grant written ahead of time and stops only when a grant is missing or an action cannot be undone.
- **Open Policy Agent.** OPA is a general policy engine with its own language and wide adoption. accountable-surface has a fixed grant format aimed at agent actions, and it also runs the action, checks it and rolls it back.
- **Playwright MCP and computer-use tools.** These give an agent a browser or a screen with no permission layer. accountable-surface can drive Playwright behind a grant, with fewer actions available.

## Install

```bash
pip install accountable-surface
pip install "accountable-surface[server]"    # adds the MCP server
pip install "accountable-surface[browser]"   # adds Playwright for BrowserEffector
```

Requires Python 3.10+. PyPI 0.3.1 is published by a trusted-publisher workflow with PEP 740 attestations, so the index records which workflow built the files.

From source, with the examples and the web UI:

```powershell
git clone https://github.com/HarperZ9/accountable-surface.git
cd accountable-surface
python -m pip install -e ".[test,server]"
$env:PYTHONPATH = "src"
python examples/actuate_demo.py
python -m pytest
```

The editable install pulls `coherence-membrane` and `proof-surface` from PyPI. CI puts sibling checkouts of both repositories on `PYTHONPATH` to test against their `main` branches.

GitHub releases for 0.1.0 and 0.2.0 carry the wheel, the sdist and a checksum file. To install the 0.2.0 wheel and check it against the published checksum:

```powershell
& {
  $ErrorActionPreference = 'Stop'

  $Version = "0.2.0"
  $Wheel = "accountable_surface-$Version-py3-none-any.whl"
  $PinnedWheelSha256 = "f2fb09ac66d00bb188da7fdd6fd1ba37485f5fe245c0596902adc355f6bccdfa"
  $Base = "https://github.com/HarperZ9/accountable-surface/releases/download/v$Version"

  Invoke-WebRequest "$Base/SHA256SUMS.txt" -OutFile SHA256SUMS.txt
  Invoke-WebRequest "$Base/$Wheel" -OutFile $Wheel

  $WheelPattern = [regex]::Escape($Wheel)
  $ChecksumRows = @(Select-String -Path SHA256SUMS.txt -Pattern "^\s*([0-9A-Fa-f]{64})\s+\*?$WheelPattern\s*$")
  if ($ChecksumRows.Count -ne 1) { throw "Expected exactly one SHA256SUMS row for $Wheel; found $($ChecksumRows.Count)" }

  $Expected = [regex]::Match($ChecksumRows[0].Line, "^\s*([0-9A-Fa-f]{64})\s+").Groups[1].Value.ToLowerInvariant()
  if ($Expected -ne $PinnedWheelSha256) { throw "SHA256SUMS row for $Wheel did not match the pinned GitHub release hash" }

  $Actual = (Get-FileHash $Wheel -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($Actual -ne $Expected) { throw "SHA256 mismatch for $Wheel" }

  python -m pip install $Wheel
}
```

## More examples

From a source checkout with `src` on `PYTHONPATH`:

- `examples/demo.py`: reads a local page, then shows a grant allowing one action and refusing another, and prints the log.
- `examples/actuate_demo.py`: a refused write, an allowed write, and a faulty write caught and rolled back.
- `examples/web_actuate_demo.py`: form filling against a local server.
- `examples/spa_actuate_demo.py`: the browser path on a JavaScript page, offline.
- `examples/goal_demo.py`: a multi-step plan under one grant that halts at the first refused or failed step.
- `examples/grounding_demo.py`, `examples/grounded_actuate_demo.py`: scoring whether an action's stated reason has supporting references.
- `examples/smoke_mcp.py`, `examples/interop_mcp_demo.py`: MCP round trips.

## Worked example

A grant is a plain JSON object. The surface acts only when the gate allows the exact plan, then verifies the effect on disk.

```python
from accountable_surface import AccountableSurface, FilesystemEffector

grant = {
    "authorization_version": "0.1",
    "receipt_id": "rcpt-example",
    "kind": "authorization-grant",
    "principal": {"id": "alice", "role": "owner"},
    "agent": {"id": "example-agent"},
    "intent": "write the report file",
    "scope": {"allowed_actions": ["fs.write"], "allowed_targets": []},
    "granted_at": "2026-06-19T00:00:00+00:00",
    "expires_at": "2030-01-01T00:00:00+00:00",
    "revoked": False,
}

surface = AccountableSurface()
out = surface.actuate(
    FilesystemEffector("/path/to/sandbox"),
    target="/path/to/sandbox/report.txt",
    content=b"written natively, verified by re-perceiving",
    authorization=grant,
)
print(out.acted, out.decision, out.verified)  # True allow True
```

With `authorization={}` the same call returns `acted=False, decision="deny"` and the file is never created. A faulty effector that writes the wrong bytes is caught at verification and rolled back; `examples/actuate_demo.py` shows both paths.

<img src="docs/art/actuation-lane.svg" alt="Eight stages of one actuation: perceive, preview, gate, act, re-perceive, verify, roll back, journal. The target is read first, so there is a witnessed record of what it looked like before anything ran. The preview describes the intended write and content-addresses it, with no side effect. The gate answers allow, deny, or needs a human, against the operator's grant. The effector acts only on an allow that names this exact plan, and only inside the root it was constructed with. The target is then read back off disk. Verification compares what landed against the digest that was authorized. A reversible action that fails verification is undone, and the target is read once more. The journal records both digests, the decision and the verdict. Three outcomes: acted and verified, not acted, and rolled back." width="100%">

## What each verdict contributes

One actuation produces up to three verdicts: what the gate decided, what the re-read found, and how well the premise was grounded. They are composed into a single certificate by a lattice meet, so a worse step can never be laundered into a better result.

<img src="docs/art/verdict-composition.svg" alt="Ten rows mapping each verdict the surface produces onto what it contributes to the composed certificate. A gate allow, a passing effect and a grounded premise each contribute verified. A gate denial, a failed effect, a refusal by the effector and an ungrounded premise each contribute refuted, and one refuted input makes the whole certificate refuted. An escalation to a human and a weak premise contribute unverifiable, which pulls a verified result down without making it false. The last row is accented: a verdict string none of the maps recognizes becomes unverifiable rather than raising." width="100%">

## Run as an MCP server

```powershell
pip install "accountable-surface[server]"
accountable-surface-server
```

Client configuration:

```json
{
  "mcpServers": {
    "accountable-surface": {
      "command": "accountable-surface-server",
      "env": {
        "ACCOUNTABLE_SURFACE_GRANTS": "/path/to/grants.json",
        "ACCOUNTABLE_SURFACE_JOURNAL": "/path/to/session-journal.jsonl",
        "ACCOUNTABLE_SURFACE_AUTHORITY_STATE": "/path/to/authority-state.sqlite3"
      }
    }
  }
}
```

### Interoperable stdio server (no FastMCP)

For adoption by other harnesses, `accountable_surface.interop_mcp` is a stdlib-only
JSON-RPC-over-stdio server: no FastMCP, nothing extra to install for a client to spawn
it and list tools. Its tools are `perceive`, `propose`, `actuate`, `device_ls`,
`journal`, `receipt`, `status` and `doctor`. The only action wired today is a
read-only directory listing (`device_ls`), which needs the separate Node
native-control tool. Each action writes an `action-receipt/v1` record that
`verify_action_receipts.py` checks offline.

```powershell
python -m accountable_surface.interop_mcp   # or: accountable-surface-mcp
```

Configuration snippets for Claude Code, Codex, Cursor and Flywheel live in `interop/`;
the overview and a test-cited comparison with ungated computer use are in
`docs/interop-mcp.md`. The hard exclusions (CAPTCHA solving, anti-bot stealth /
fingerprint patching, reCAPTCHA token harvest, mass or obfuscated authenticated
outreach) are unreachable through any tool and asserted by test.

`ACCOUNTABLE_SURFACE_GRANTS` points to a JSON file with one grant or a list;
with none loaded every action is refused. Remote reads are scoped
separately from writes: `allowed_actions` may name `fs.write`, but the remote
server still refuses until `allowed_reads` covers the target state phases it must
read (`before`, `backup`, `after`, and `rollback` for filesystem writes).
`ACCOUNTABLE_SURFACE_JOURNAL` points to an append-only JSONL file; when set, the
journal replays on launch so the witnessed self-view spans sessions.

`ACCOUNTABLE_SURFACE_AUTHORITY_STATE` points to an optional stdlib-SQLite state file for durable revocation, atomic usage reservations, and idempotency. With it set, remote `actuate` requires an `idempotency_key`, refuses protected grant/state/journal paths even under broad filesystem grants, and keeps unresolved precommit reservations unavailable until you recover them manually. See [docs/durable-authority.md](docs/durable-authority.md).

`ACCOUNTABLE_SURFACE_EFFECTORS` points to a JSON file naming which effectors a remote caller may reach:

```json
{"effectors": [
  {"action_kind": "fs.write", "type": "filesystem", "root": "/srv/agent-sandbox"},
  {"action_kind": "api.post", "type": "api", "service": "github"}
]}
```

Three settings guard remote `actuate` and all have to agree: the
registry exposes an effector, `allowed_actions` names the write, and
`allowed_reads` names the state reads needed to precondition, verify, and roll
back that write. With the variable unset, the file empty, or the action kind
missing from it, `actuate` refuses before it reads a grant. The file refuses
`command`, `browser`, `web`, and `uia` by name, each with the reason. Ask
`doctor` for the exposed set, the reach of each entry, and the entries it turned
down. MCP `perceive` likewise needs a `web.document` read grant, and full
`session_journal` replay needs a `journal.session` read grant.

## Shared world server

A local web UI where you can watch an agent work: each proposed action runs the full check, act and verify loop and streams over SSE to every open tab. It needs a source checkout, because the `web/` files are not in the wheel. The token, Host and Origin checks below are on `main` and not yet in PyPI 0.3.1.

```powershell
python -m accountable_surface.world.server 8808
```

It serves the web UI from `web/`. Open the URL it prints: the URL carries a token that is new on every run. The server binds loopback only and refuses any other host. Every API request needs the token (header `X-World-Token`), and a request whose Host or Origin is not the server's own is refused, so another web page you visit cannot drive the world. Grants are loaded at startup. With none supplied, it uses a demo grant scoped to its sandbox folder, and anything outside that grant is refused.

## Layout

- `src/accountable_surface/surface.py`: `AccountableSurface` with `perceive`, `propose`, `actuate`, `pursue`, `interocept`, and the durable journal.
- `effector.py`, `web_effector.py`, `browser_effector.py`, `os_effector.py`, `api_effector.py`, `uia_effector.py`, `native_control_effector.py`: the effectors and their drivers.
- `http_driver.py`: the stdlib HTTP and HTML backend behind native web actuation.
- `playwright_driver.py`: the optional JS-capable browser driver.
- `reference.py`: the grounding cortex, `certify.py`: action certificates, `grant.py`: grant helpers.
- `server.py`: the MCP server. `world/`: the shared world session, server, sight, and pilots.
- `tests/`: the Python test suite. `examples/`: nine runnable scripts. `web/`: the shared world UI plus Node tests.
- `docs/`: design specs (`SPEC-actuation.md`, `SPEC-interoception.md`, `SPEC-persistence.md`), design notes, and [docs/INTRODUCTION.md](docs/INTRODUCTION.md), the first-ten-minutes guide.
- `docs/art/`: the diagrams above, rendered from `accountable-surface.art.json` by `tools/render_repo_art.py` and checked by `tools/check_repo_art.py`. Brand assets: `docs/art/` (hero, social preview) and `docs/brand/` (mark, lockups).

## Status

Alpha. PyPI has 0.3.1; `main` carries the unreleased changes listed in [CHANGELOG.md](CHANGELOG.md). The API is settling and may change between 0.x releases. CI runs the Python suite and the Node web tests on every push and pull request, with sibling checkouts of coherence-membrane and proof-surface. Local verification:

```powershell
$env:PYTHONPATH = "src;..\coherence-membrane\src;..\proof-surface\src"
python -m pytest
node --test web/*.test.mjs
```

Release packaging steps and hold points are in [docs/RELEASE.md](docs/RELEASE.md).

## Related repos

- [coherence-membrane](https://github.com/HarperZ9/coherence-membrane): the perception organs and certificate types this surface composes.
- [proof-surface](https://github.com/HarperZ9/proof-surface): the pre-execution gate (allow, deny, needs-human).
- [USAGE.md](USAGE.md): the operational guide, including the browser backend.

## Development disclosure

Zain Dana Harper maintains this repository. AI-assisted tools are used for
parts of development and documentation. Public source, tests, and release
artifacts are the evidence for what ships; AI output is not treated as proof.

## How the journal chain works

A journal that can be quietly rewritten records nothing worth reading. Each entry is chained to the one before it, so an edit breaks the entry's own hash and a delete or a reorder breaks the link to its neighbour. `verify_journal.py` re-derives the whole chain with no import from this package, which means a stranger holding only the JSONL file can check it.

<img src="docs/art/journal-chain-lane.svg" alt="Eight stages of the journal chain: entry, canonical, chain hash, append, reload, edit, move, verdict. An entry is a kind, a summary and a detail, and nothing outside those three is hashed. The entry is serialized one way only, with sorted keys and no spaces, so the same content always produces the same bytes. Its chain hash is taken over the previous entry's hash together with those bytes. The line is appended as one compact JSON object. On reload every line is parsed and rechained from the genesis anchor. An edited field no longer hashes to the record that carries it. A deleted or reordered entry breaks the link to the running head. The verdict counts unparseable lines separately from chain breaks, and never merges the two. Three outcomes: match, drift, and unverifiable." width="100%">

## License

Text: CC BY 4.0. Code: FSL-1.1-MIT.

[`THESIS.md`](THESIS.md) is a written work and is licensed CC BY 4.0. Share and
adapt it with credit to Zain Dana Harper; the terms are in
[`LICENSE-TEXT`](LICENSE-TEXT). The code and the software documentation are
FSL-1.1-MIT. Copyright (c) 2026 Zain Dana Harper. See [LICENSE](LICENSE).

## What this believes

This tool is one lane of a family that holds a single belief steady across
every surface: knowledge open to anyone who can attain the means; acceptance
decided by external checks, never reputation; every result re-runnable;
honest nulls first-class; ownership earned by comprehension; learning woven
into the work. The full text lives in [CREDO.md](CREDO.md).
The long form of this belief: [The Unbundling](https://github.com/HarperZ9/flywheel/blob/main/docs/essays/2026-07-13-the-unbundling.md).

---

Built by **[Zain Dana Harper](https://harperz9.github.io)** in Seattle: evidence-first tools that leave a re-checkable artifact behind. The full workbench is at [Project Telos](https://harperz9.github.io).
