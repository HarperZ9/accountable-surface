"""interop_mcp.py -- an interoperable, action-capable MCP stdio server for the
accountable-actuation core, so other harnesses (Claude Code, Codex, Cursor, the
Flywheel bundled lane) adopt one seam: witnessed perception, a pre-execution gate, a
bounded act, an independent self-verify, a tamper-evident journal, and an
offline-re-derivable action receipt. See docs/interop-mcp.md.

Zero third-party dependency in the PROTOCOL layer: JSON-RPC 2.0 over stdio, stdlib
only, no FastMCP. A harness spawns ``python -m accountable_surface.interop_mcp`` and
gets the tools with nothing to pip install beyond the core surface. The action tools
need the runtime (the surface plus coherence-membrane and proof-surface); this module
imports it LAZILY, so ``initialize``, ``tools/list``, ``status``, and ``doctor``
answer even without it, and the action tools return a named error rather than failing
to start. The streamable-HTTP / Muse remote path is documented; stdio is what ships.

SAFE SUBSET ONLY. The server reaches exactly the verbs in ``SAFE_READ_VERBS`` (today,
``device ls``). ``EXCLUDED_CAPABILITIES`` names the classes unreachable by
construction -- CAPTCHA solving, anti-bot stealth / fingerprint patching, reCAPTCHA
token harvest, mass or obfuscated authenticated outreach -- and no argument reaches
one. The allowlist is the boundary; the denylist is a second, explicit assertion.
"""

from __future__ import annotations

import json
import platform
import sys
from typing import Any

MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "accountable-surface"
_SURFACE = "interop-stdio"

# The runtime the action tools need. doctor probes these by name only (find_spec
# never executes them), so it reports reachability while itself staying stdlib.
_RUNTIME_DEPS = ("coherence_membrane", "proof_surface")

# --- the six accountable primitives, and the tool that carries each -----------
# "gate" is the decision propose returns (allow / deny / needs-human); it is not a
# separate call, so it maps to the propose tool. actuate re-runs the gate itself.
PRIMITIVES: dict[str, str] = {
    "perceive": f"{SERVER_NAME}.perceive",
    "propose": f"{SERVER_NAME}.propose",
    "gate": f"{SERVER_NAME}.propose",
    "actuate": f"{SERVER_NAME}.actuate",
    "journal": f"{SERVER_NAME}.journal",
    "receipt": f"{SERVER_NAME}.receipt",
}

# --- HARD EXCLUSIONS ----------------------------------------------------------
# The capability classes this bridge will never reach, grouped for the doctor
# report. These are labels for the boundary, not a menu: no tool accepts them, the
# runtime refuses them before any subprocess, and the effector will not even
# construct for a verb outside SAFE_READ_VERBS. Asserted unreachable in
# tests/test_interop_exclusions.py.
EXCLUDED_CAPABILITIES: dict[str, list[tuple[str, str]]] = {
    "captcha_solving": [("browser", "captcha"), ("browser", "recaptcha_solve")],
    "anti_bot_stealth": [("browser", "behave"), ("browser", "stealth"), ("browser", "fingerprint")],
    "token_harvest": [("browser", "token"), ("browser", "recaptcha_token")],
    "mass_outreach": [("gmail", "send_bulk"), ("linkedin", "post"), ("browser", "targets"),
                      ("browser", "autofill"), ("email", "mass")],
    "mutating_device": [("device", "exec"), ("device", "write")],
}
EXCLUDED_VERBS: frozenset[tuple[str, str]] = frozenset(
    pair for pairs in EXCLUDED_CAPABILITIES.values() for pair in pairs
)


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _text_result(payload: Any, *, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, sort_keys=True)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def server_version() -> str:
    """Best-effort version without hard-requiring the runtime import to succeed."""
    try:
        from accountable_surface import __version__

        return __version__
    except Exception:  # noqa: BLE001 - identity must answer even without the runtime.
        try:
            from importlib.metadata import version

            return version("accountable-surface")
        except Exception:  # noqa: BLE001
            return "0.0.0+unknown"


def _dep_reachable(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def status_payload() -> dict:
    """Network-free identity: who this server is, that it admits the runtime, and the
    tools and primitives it carries. No perception, no gate, no actuation."""
    return {
        "ok": True,
        "server": SERVER_NAME,
        "version": server_version(),
        "surface": _SURFACE,
        "admits_runtime": True,
        "transport": "stdio",
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "tools": [t["name"] for t in _tool_defs()],
        "primitives": dict(PRIMITIVES),
    }


def doctor_payload() -> dict:
    """Readiness: identity, the tools, the runtime dependency probe, the hard
    exclusions, and -- when the runtime is importable -- grants loaded, the wired
    safe verbs, and the receipt store. Never runs an action."""
    deps = {name: _dep_reachable(name) for name in _RUNTIME_DEPS}
    payload: dict[str, Any] = {
        "ok": True,
        "server": SERVER_NAME,
        "version": server_version(),
        "surface": _SURFACE,
        "admits_runtime": True,
        "transport": "stdio",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tools": [t["name"] for t in _tool_defs()],
        "primitives": dict(PRIMITIVES),
        "runtime_dependencies": deps,
        "runtime_reachable": all(deps.values()),
        "excluded_capabilities": {k: [f"{d}.{v}" for d, v in pairs]
                                  for k, pairs in EXCLUDED_CAPABILITIES.items()},
    }
    try:
        from accountable_surface.interop_runtime import default_interop

        payload["runtime"] = default_interop().doctor_runtime()
    except Exception as exc:  # noqa: BLE001 - degrade to a health-only report.
        payload["runtime"] = {"available": False, "reason": f"runtime not loaded: {exc}"}
    return payload


def _tool(name: str, description: str, properties: dict | None = None,
          required: list[str] | None = None) -> dict:
    schema: dict[str, Any] = {"type": "object"}
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return {"name": f"{SERVER_NAME}.{name}", "description": description, "inputSchema": schema}


_STR = {"type": "string"}


def _tool_defs() -> list[dict]:
    """The eight tools. perceive/journal/receipt/status/doctor are pure reads; propose
    is the advisory gate; actuate and device_ls run the gated loop for a wired safe verb."""
    return [
        _tool("perceive", "Witness a subject as an Observation with its provenance digest: a "
              "directory (independent os.scandir witness) or a web page / file. No gate, no act.",
              {"subject": _STR}, ["subject"]),
        _tool("propose", "Run the pre-execution GATE for (action_kind, target) against the operator's "
              "grants; returns allow / deny / needs-human. The model cannot self-authorize; "
              "default-deny with no grant. Never acts.",
              {"action_kind": _STR, "target": _STR, "expected_digest": _STR}, ["action_kind", "target"]),
        _tool("actuate", "The full loop for a wired SAFE verb: perceive -> plan -> gate -> act -> "
              "re-perceive -> independent verify -> journal -> emit an action-receipt/v1. Only "
              "native.device.ls is wired; anything else is refused. Rolls back a failed reversible act.",
              {"action_kind": _STR, "target": _STR, "content": {"type": "array", "items": _STR},
               "expected_digest": _STR, "idempotency_key": _STR}, ["action_kind", "target"]),
        _tool("device_ls", "The shipped read-only verb: list a directory through the accountable loop "
              "(native.device.ls), checked against the surface's own independent witness. Takes a path.",
              {"path": _STR}, ["path"]),
        _tool("journal", "Return this session's journal (perceptions, gate decisions, actuations) with "
              "a re-derived chain-integrity verdict. A pure read."),
        _tool("receipt", "Re-derive the action-receipt/v1 store offline: MATCH / DRIFT / UNVERIFIABLE, "
              "with the store path. Set include_events to also return the (redacted) events.",
              {"include_events": {"type": "boolean"}}),
        _tool("status", "Network-free identity: name, version, tools, primitives. A fast liveness probe."),
        _tool("doctor", "Readiness: identity, tools, the runtime dependency probe, the hard exclusions, "
              "and (when the runtime loads) grants, wired safe verbs, and the receipt store."),
    ]


def call_tool(name: str, args: dict) -> tuple[Any, bool]:
    """Dispatch a tool by name. Returns (payload, is_error). Health tools answer with
    no runtime; the action tools import the runtime lazily and return a named error
    (never a crash) when it is unavailable."""
    short = name.split(".", 1)[1] if name.startswith(SERVER_NAME + ".") else name
    if short == "status":
        return status_payload(), False
    if short == "doctor":
        return doctor_payload(), False
    try:
        from accountable_surface.interop_runtime import default_interop

        interop = default_interop()
    except Exception as exc:  # noqa: BLE001
        return {"error": "runtime unavailable",
                "detail": f"{exc}",
                "hint": "install the core surface (coherence-membrane + proof-surface); "
                        "see docs/interop-mcp.md"}, True
    if short == "perceive":
        return interop.perceive(str(args["subject"])), False
    if short == "propose":
        return interop.propose(str(args["action_kind"]), str(args["target"]),
                               args.get("expected_digest")), False
    if short == "actuate":
        return interop.actuate(str(args["action_kind"]), str(args["target"]),
                               content=args.get("content"),
                               expected_digest=args.get("expected_digest"),
                               idempotency_key=args.get("idempotency_key")), False
    if short == "device_ls":
        return interop.device_ls(str(args["path"])), False
    if short == "journal":
        return interop.journal(), False
    if short == "receipt":
        return interop.receipt(include_events=bool(args.get("include_events", False))), False
    raise ValueError(f"unknown tool: {name!r}")


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    mid = req.get("id")
    if "id" not in req:  # a notification -- no response.
        return None
    if method == "initialize":
        return _ok(mid, {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {"tools": {}},
                         "serverInfo": {"name": SERVER_NAME, "version": server_version()}})
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
            payload, is_error = call_tool(name, params.get("arguments") or {})
            return _ok(mid, _text_result(payload, is_error=is_error))
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


def main() -> int:
    """Console entry point -- run the interop server over stdio."""
    return serve()


if __name__ == "__main__":  # pragma: no cover - a launcher entry point.
    raise SystemExit(main())
