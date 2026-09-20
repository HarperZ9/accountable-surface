# Add the accountable-surface MCP server to your harness

One stdio MCP server exposes the accountable-actuation seam: witnessed perception, a
pre-execution gate (allow / deny / needs-human), a reach-bounded act, an independent
self-verify (MATCH / DRIFT / UNVERIFIABLE), a tamper-evident journal, and an
offline-re-derivable action receipt. Read-only `device ls` is wired today. Write-class
actuation and broad browser / app / device breadth are target, not shipped.

The protocol layer is stdlib-only JSON-RPC over stdio (no FastMCP). A harness spawns
`python -m accountable_surface.interop_mcp` and gets the tools with nothing to pip
install beyond the core surface. `initialize`, `tools/list`, `status`, and `doctor`
answer even where the action runtime is not installed; the action tools load it lazily
(the sibling repos coherence-membrane and proof-surface) and return a named error
otherwise. See `../docs/interop-mcp.md` for the overview and the evidence-bound
comparison over ungated computer use.

## Environment

| Variable | Purpose |
| --- | --- |
| `ACCOUNTABLE_SURFACE_GRANTS` | Path to the operator's authorization-grant JSON. Without a grant naming an `action_kind`, actuation is default-deny. The model never supplies authorization. |
| `ACCOUNTABLE_SURFACE_JOURNAL` | Optional. Append-only, hash-chained journal path. Unset keeps the surface in-memory. |
| `ACCOUNTABLE_SURFACE_RECEIPTS` | Optional. Append-only action-receipt/v1 store path. Defaults beside the journal, else a per-process temp file. |
| `ACCOUNTABLE_SURFACE_NATIVE_CONTROL_SCRIPT` | Path to the telos `native-control.mjs` actuator. Required to actuate `device ls` for real; unset yields a clean refusal. |

If the core surface is not pip-installed, put its sources on `PYTHONPATH`:
`.../accountable-surface/src`, `.../coherence-membrane/src`, `.../proof-surface/src`.

## Claude Code

Copy `claude-code.mcp.json` into your project's `.mcp.json` (or merge its
`mcpServers` block), fill the env paths, and reload. Verify with the `doctor` tool.

## Codex

Codex reads MCP servers from `~/.codex/config.toml`. Add:

```toml
[mcp_servers.accountable-surface]
command = "python"
args = ["-m", "accountable_surface.interop_mcp"]

[mcp_servers.accountable-surface.env]
ACCOUNTABLE_SURFACE_GRANTS = "/absolute/path/to/operator-grants.json"
ACCOUNTABLE_SURFACE_JOURNAL = "/absolute/path/to/journal.jsonl"
ACCOUNTABLE_SURFACE_RECEIPTS = "/absolute/path/to/action-receipts.jsonl"
ACCOUNTABLE_SURFACE_NATIVE_CONTROL_SCRIPT = "/absolute/path/to/telos/demo/native-control.mjs"
```

## Cursor

Cursor reads `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project). The shape
matches `claude-code.mcp.json` -- one `mcpServers.accountable-surface` stdio entry
with `command`, `args`, and `env`. Reuse that file.

## Flywheel (bundled lane)

`flywheel-lane.json` is the data behind a Flywheel `Lane`. Add this line to the `LANES`
registry in `flywheel/harness/lanes_registry.py`:

```python
"accountable-surface": Lane(
    "accountable-surface", "accountable-surface", "python",
    ("-m", "accountable_surface.interop_mcp"), "bundled", "0.2.0",
    "accountable actuation: gate + independent verify + rollback + offline-re-derivable receipt over MCP",
    "actuation", source_repo="public/accountable-surface",
    py_module="accountable_surface.interop_mcp",
    extra_source_repos=("public/coherence-membrane", "public/proof-surface")),
```

The roster marks the lane live when its `accountable-surface.status` health tool
answers, which this server advertises.

## Generic MCP client

`mcp-server.json` is a transport-neutral descriptor (command, protocol version, tools,
primitives, exclusions) for any other MCP host. Launch over stdio:
`python -m accountable_surface.interop_mcp` (or the `accountable-surface-mcp` console
script once installed).

## Remote / streamable-HTTP (Muse)

stdio is what ships. The streamable-HTTP path for a remote effector (Muse) is described
in `../docs/interop-mcp.md`; the durable-authority, read-authority, and protected-path
controls it needs are the ones already in `accountable_surface.server` and
`accountable_surface.authority_store`.
