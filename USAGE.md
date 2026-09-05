# Accountable Surface Usage

## What It Is

Accountable Surface is a local action workbench for AI agents. It lets a host
runtime observe a target, propose an action, check that action against an
operator-loaded grant, execute only through a bounded effector, verify the
result, and record the journal.

## Clone With Sibling Repositories

The core package composes with `coherence-membrane` and `proof-surface`.

```powershell
git clone https://github.com/HarperZ9/accountable-surface.git
git clone https://github.com/HarperZ9/coherence-membrane.git
git clone https://github.com/HarperZ9/proof-surface.git
cd accountable-surface
```

## Install For Development

```powershell
$env:PYTHONPATH = "src;..\coherence-membrane\src;..\proof-surface\src"
python -m pip install -e ".[test]"
```

## Run The Local Checks

```powershell
python -m pytest
node --test web/*.test.mjs
```

## Run The Basic Demo

```powershell
python examples/demo.py
python examples/actuate_demo.py
```

## Run As An MCP Server

```powershell
python -m pip install -e ".[server]"
$env:PYTHONPATH = "src;..\coherence-membrane\src;..\proof-surface\src"
python -m accountable_surface.server
```

MCP client example:

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

## Exposing An Effector Over MCP

`perceive`, `propose`, `session_journal`, and `interocept` are always available.
`actuate` writes, so it reaches only what the operator has exposed. Point
`ACCOUNTABLE_SURFACE_EFFECTORS` at a JSON file:

```json
{"effectors": [
  {"action_kind": "fs.write", "type": "filesystem", "root": "/srv/agent-sandbox"},
  {"action_kind": "api.post", "type": "api", "service": "github"}
]}
```

A caller then asks for one action kind at a time:

```json
{"action_kind": "fs.write", "target": "/srv/agent-sandbox/notes.md", "content": "hello"}
```

`content` is the text for a file write. For an api entry it is
`{"intent": "post_comment", "body": {...}}`, so the caller names an operation the
service declares and never a host, a header, or a route.

The reply carries the gate decision, the verify verdict, the composed certificate,
and the journal entry for that one call. The rest of the journal stays with the
operator, and `session_journal` is where the operator reads it.

Two decisions guard the call and both have to agree. This file says what a caller
can reach at all; the grant says what may be done with it. Leave the variable unset
and `actuate` refuses everything, however wide the grants are. The file refuses
`command`, `browser`, `web`, and `uia` by name, each with the reason. Run `doctor` to see
the exposed set, the reach of each entry, and the entries it turned down, so nobody
has to guess at an empty registry.

## Using The Browser Backend (JS-Capable SPAs)

`WebEffector` drives server-rendered pages natively (stdlib, zero-dep) but runs no
JavaScript. `BrowserEffector` adds a JS-capable edge: click by accessible label,
follow cross-origin navigation, and run JS on a live single-page app -- all through
the same gate + verify + rollback + journal contract.

The browser backend is injectable. Tests and offline demos use the deterministic,
zero-dependency `FakeBrowserDriver`; production injects the optional
`PlaywrightDriver`.

Tests (deterministic, offline -- the default):

```python
from accountable_surface import AccountableSurface, BrowserEffector, FakeBrowserDriver, BrowserAction

driver = FakeBrowserDriver(start="https://app.test/")
eff = BrowserEffector(driver, allowed_origins=["https://app.test"])
AccountableSurface().actuate(
    eff, target="https://app.test/",
    content=BrowserAction("navigate", url="https://app.test/dashboard"),
    authorization=grant,  # operator-loaded; no grant -> default-deny
)
```

Production (real headless Chromium -- optional, lazily imported):

```powershell
python -m pip install "accountable-surface[browser]"
python -m playwright install chromium
```

```python
from accountable_surface.playwright_driver import PlaywrightDriver

driver = PlaywrightDriver(headless=True, start="https://app.example.com/")
eff = BrowserEffector(driver, allowed_origins=["https://app.example.com"])
# ...same surface.actuate() contract, now with real JS execution.
```

Playwright is never a hard dependency: it is imported only when `PlaywrightDriver`
is instantiated, so the default install and the whole test suite stay zero-dep.
Run the offline SPA transcript with `python examples/spa_actuate_demo.py`.

## Writing Through A Third-Party API

`ApiEffector` covers the case where the work belongs on someone else's service and
that service has an official write API. The agent names an intent, never a route:

```python
from accountable_surface import (
    AccountableSurface, ApiCall, ApiEffector, GITHUB_ISSUE_COMMENTS,
)
from accountable_surface.api_transport import UrllibApiDriver

eff = ApiEffector(UrllibApiDriver(), GITHUB_ISSUE_COMMENTS)
AccountableSurface().actuate(
    eff,
    target="/repos/octo/demo/issues/7/comments",
    content=ApiCall("post_comment", {"body": "found a repro, steps below"}),
    authorization=grant,  # scope.allowed_actions must carry "api.post"
)
```

The service object declares every write that is possible at all. An intent it does
not list is refused, and a target the intent's path shape does not match is refused,
so `post_comment` cannot reach a collaborator or settings route on the same host.

The credential is a variable name in the service definition. Its value is read from
the environment at the moment of the call and sent in a header, so it never appears
in a Plan, an Observation, the journal, or an error message. Set it before the run:

```powershell
$env:ACCOUNTABLE_SURFACE_GITHUB_TOKEN = "<a token with the narrowest scope that works>"
```

Verification re-reads the collection and looks for a member carrying the body that
was authorized. The response to the write is never consulted, so a service that
answers 201 and stores nothing comes back REFUTED.

Swap `UrllibApiDriver` for `FakeApiDriver` to exercise the whole path offline with
no network and no credential, the way the test suite does.

## Acting On A Windows Application

`UiaEffector` reaches a desktop application through its control tree rather than
through the screen. The effector is built for one window and reads only that window:

```python
from accountable_surface import AccountableSurface
from accountable_surface.uia_effector import UiaCommand, UiaEffector
from accountable_surface.uia_transport import PowerShellUiaDriver

eff = UiaEffector(PowerShellUiaDriver(path_to_uia_script), "Notepad")
AccountableSurface().actuate(
    eff,
    target="uia://Notepad/Message",
    content=UiaCommand("set_value", text="the text to type into that field"),
    authorization=grant,  # scope.allowed_actions must carry "uia.set_value"
)
```

Two intents, so a grant can carry the reversible one on its own. `set_value` reads
the control's prior value first and puts it back when verification fails. `invoke`
presses the control and cannot be undone, so it stays `needs-human` unless the
operator passes `allow_irreversible`, and it needs a declared post-condition:

```python
UiaCommand("invoke", expect={"kind": "appears", "element": "Saved"})
```

The other two post-conditions are `disappears` and `value_is`. A plan carrying none
of them is refused at preview time, because a press nobody can check is a press
nobody can authorize. Verification re-reads the window; the instrument reports `ok`
for anything it dispatched, so its own account of its work is never consulted.

A control tree the walk had to clip comes back UNVERIFIED, and a `disappears` check
against a clipped tree fails rather than reading the missing control as gone. Two
controls sharing one accessible name resolve to whichever the walk reached first,
which is an open null recorded in `tests/test_false_success.py`.

What this repo ships is the driver contract, the two rungs above it, and
`FakeUiaDriver`. The PowerShell script itself is supplied by the operator: it answers
JSON on stdout for `tree`, `value`, `invoke`, and `setvalue`, and exits 0 whatever
happened, so a refusal arrives as data. The transport refuses the blind keystroke
verbs `input` and `type` by name before it spawns anything, because they name no
control and nothing about them can be verified by re-reading a tree.

Honest null: the subprocess path has no test coverage. Exercising it needs Windows, a
live window, and a running application. Swap `PowerShellUiaDriver` for `FakeUiaDriver`
to run the whole path on any operating system with no window open, the way the test
suite does, and treat a first real call as unproven.

## Choosing A Rung

`structure_ladder` climbs from the control tree to the screen and records why it
fell:

```python
from accountable_surface.escalator import Question, structure_ladder
from accountable_surface.uia import UiaStructureOrgan

ladder = structure_ladder(UiaStructureOrgan(driver), "Notepad", capture)
ascent = ladder.resolve(Question("present", "Save"))
print(ascent.answer)      # True, False, or None when nothing settled it
print(ascent.trace())
```

A whole control tree settles the question either way: the label resolves, or it does
not and the tree was complete. A clipped tree falls instead, because a control that
exists can be sitting past the cut.

```
rung 0 structure (low cost): fell -- the walk clipped the tree at the 400-control limit, so absence is not established
rung 3 pixels (high cost): fell -- pixels carry no control names, so 'Save' cannot be resolved from them; the sight is witnessed at phash <16 hex chars>
```

When the ladder runs out, `ascent.status` is NEEDS_HUMAN, `ascent.rederivable` is
`"none"`, and `ascent.witness` carries the sight the deepest rung produced. That sight
has a content digest and a perceptual hash and answers nothing about a control named
`Save`. Reading it is a person's job.

The escalator only reads. Rungs 1 and 2 act, and acting stays with the effectors and
the grants that bound them, so nothing here presses a control to find out what it does.

## Boundary

- No grant means default deny.
- The model cannot provide its own authorization.
- Over MCP, an effector the operator has not exposed cannot be reached under any grant.
- `uia` is not exposable over MCP at all. It acts on a window belonging to whoever
  is at the machine, and reaching that from off the machine is a separate decision.
- Over MCP, an irreversible action stays `needs-human`. No argument a remote caller
  passes reaches `allow_irreversible`.
- Journals are append-only local records.
- Operator grant files and session journals are runtime inputs, not source files.
- Irreversible actions require explicit grant handling and verification.
