"""mcp.py -- the Accountable Surface's bundled-lane MCP stdio surface (stdlib only).

A zero-dependency JSON-RPC-over-stdio shim that mirrors the ecosystem's bundled-lane
MCP shape (see ``gather.mcp`` / ``chorus.mcp``). It advertises the network-free
health tools ``accountable-surface.status`` and ``accountable-surface.doctor`` so a
lane roster can mark the lane live and read its readiness without admitting the full
runtime.

This surface admits NO runtime. It never perceives, gates, or actuates, and it never
imports the live server (``accountable_surface.server``, which needs the ``mcp`` /
FastMCP extra) nor the world server (``accountable_surface.world.server``, HTTP). It
answers identity and readiness only, and touches the standard library alone -- so a
bundled-lane launcher can start it anywhere, even where the perception/gate sibling
repos are not installed. The live, action-capable MCP server stays in ``server.py``.
"""
from __future__ import annotations

import importlib.util
import json
import platform
import sys
from typing import Any

from accountable_surface import __version__

MCP_PROTOCOL_VERSION = "2025-06-18"

SERVER_NAME = "accountable-surface"
_SURFACE = "bundled-stdio"

# The two tools this surface admits. Health only -- no perception, no gate, no
# actuation. Dotted names match the lane roster (gather.status, chorus.status).
STATUS_TOOL = "accountable-surface.status"
DOCTOR_TOOL = "accountable-surface.doctor"

# Optional runtime dependencies the live and world servers need. doctor probes
# these by name only (find_spec never executes them), so it can report whether the
# action-capable server is reachable while this surface itself stays stdlib-only.
_RUNTIME_DEPS = ("mcp", "coherence_membrane", "proof_surface")


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _dep_reachable(name: str) -> bool:
    """True when ``name`` can be imported, tested without importing it. find_spec
    inspects the finders only -- it never runs the module -- so this stays stdlib."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def status_payload() -> dict:
    """Network-free identity: who this lane is, what version, and that it admits no
    runtime. No perception, no gate, no actuation."""
    return {
        "ok": True,
        "server": SERVER_NAME,
        "version": __version__,
        "surface": _SURFACE,
        "admits_runtime": False,
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "tools": [STATUS_TOOL, DOCTOR_TOOL],
    }


def doctor_payload() -> dict:
    """Readiness: identity, the exposed tools, and basic environment checks
    (interpreter, platform, and whether the action-capable runtime is reachable)."""
    deps = {name: _dep_reachable(name) for name in _RUNTIME_DEPS}
    return {
        "ok": True,
        "server": SERVER_NAME,
        "version": __version__,
        "surface": _SURFACE,
        "admits_runtime": False,
        "tools": [STATUS_TOOL, DOCTOR_TOOL],
        "python": platform.python_version(),
        "platform": platform.platform(),
        "runtime_dependencies": deps,
        "live_server_reachable": all(deps.values()),
        "note": (
            "health-only bundled surface; the action-capable server is "
            "accountable_surface.server (needs the 'server' extra plus the "
            "coherence-membrane and proof-surface sibling repos)"
        ),
    }


def _tool_defs() -> list[dict]:
    return [
        {
            "name": STATUS_TOOL,
            "description": "Emit the Accountable Surface's network-free identity "
                           "envelope: no perception, no gate, no actuation.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": DOCTOR_TOOL,
            "description": "Report the bundled surface's readiness: identity, the "
                           "exposed tools, and basic environment checks.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def call_tool(name: str, args: dict) -> str:
    if name == STATUS_TOOL:
        return json.dumps(status_payload(), indent=2, sort_keys=True)
    if name == DOCTOR_TOOL:
        return json.dumps(doctor_payload(), indent=2, sort_keys=True)
    raise ValueError(f"unknown tool: {name!r}")


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    mid = req.get("id")
    if "id" not in req:
        return None
    if method == "initialize":
        return _ok(mid, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        })
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": _tool_defs()})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str) or name not in {t["name"] for t in _tool_defs()}:
            return _err(mid, -32602, f"unknown tool: {name!r}")
        try:
            return _ok(mid, _text_result(call_tool(name, params.get("arguments") or {})))
        except Exception as exc:  # noqa: BLE001 - a tool failure is a named, non-fatal result.
            return _ok(mid, _text_result(f"error: {exc}", is_error=True))
    return _err(mid, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    """Read line-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        response = handle_request(request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - a launcher entry point.
    raise SystemExit(serve())
