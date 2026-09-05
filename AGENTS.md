# AGENTS.md -- Accountable Surface

## Project Boundary

Accountable Surface is a public Python workbench for witnessed perception,
operator-granted action, verification, journals, and MCP integration. It is a
controlled local action surface: grants are loaded by the operator, actions are
bounded by effectors, and verification happens after each permitted action.

## Public Delivery Rules

- Keep `README.md`, `USAGE.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `AUTHORS.md`,
  `LICENSE`, `.github/FUNDING.yml`, `.github/workflows/ci.yml`, examples, docs,
  web demos, and package metadata aligned.
- Public claims must be backed by tests, examples, specs, or reproducible
  commands.
- Do not commit `.env` files, private grants, journals, local caches, raw
  transcripts, credentials, or private corpus material.
- Keep the README clear for two audiences: public users deciding what the tool
  does, and developers trying to run or extend it.

## Developer Verification

From this repo, with sibling checkouts available:

```powershell
$env:PYTHONPATH = "src;..\coherence-membrane\src;..\proof-surface\src"
python -m pip install -e ".[test]"
python -m pytest
node --test web/*.test.mjs
```

If a change touches MCP serving, run the server smoke path with the `[server]`
extra. If a change touches actuation, add or update a test that proves the
grant, effect, verification, rollback, or refusal behavior.

If a change touches what a remote caller can reach, add or update a test in
`tests/test_mcp_actuate.py` proving the registry refuses an unexposed action kind
before any grant is read.

If a change touches the Windows escalation ladder (`uia.py`, `uia_effector.py`,
`uia_transport.py`), add or update a test proving verification re-reads the window
rather than reading the instrument's own report of its work. That instrument answers
`ok` for an act it merely dispatched.

If a change touches the escalator, add or update a test proving a rung that fell does
not set the answer. The perception a deeper rung returns carries a full digest and a
perceptual hash, which is exactly what makes it tempting to read as a result.
