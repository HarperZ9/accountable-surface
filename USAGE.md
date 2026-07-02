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

## Boundary

- No grant means default deny.
- The model cannot provide its own authorization.
- Journals are append-only local records.
- Operator grant files and session journals are runtime inputs, not source files.
- Irreversible actions require explicit grant handling and verification.
