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

## Boundary

- No grant means default deny.
- The model cannot provide its own authorization.
- Journals are append-only local records.
- Operator grant files and session journals are runtime inputs, not source files.
- Irreversible actions require explicit grant handling and verification.
