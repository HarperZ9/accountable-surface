"""The bundled-lane stdio MCP surface (accountable_surface.mcp).

A zero-dependency JSON-RPC-over-stdio shim: it advertises the network-free health
tools accountable-surface.status and accountable-surface.doctor and answers a real
tools/list and tools/call round-trip, without importing the FastMCP live server or
the world server. These tests assert the contract and the health-only shape.
"""
from __future__ import annotations

import io
import json

from accountable_surface import __version__
from accountable_surface import mcp


def test_serve_and_handle_request_are_module_level_callables():
    assert callable(mcp.serve)
    assert callable(mcp.handle_request)


def test_tools_list_advertises_both_health_tools():
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["accountable-surface.status", "accountable-surface.doctor"]


def test_status_is_network_free_identity():
    resp = mcp.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "accountable-surface.status", "arguments": {}}}
    )
    body = json.loads(resp["result"]["content"][0]["text"])
    assert resp["result"]["isError"] is False
    assert body["ok"] is True
    assert body["server"] == "accountable-surface"
    assert body["version"] == __version__
    assert body["admits_runtime"] is False


def test_doctor_reports_tools_and_environment():
    resp = mcp.handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "accountable-surface.doctor", "arguments": {}}}
    )
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["ok"] is True and body["server"] == "accountable-surface"
    assert body["tools"] == ["accountable-surface.status", "accountable-surface.doctor"]
    assert isinstance(body["python"], str) and body["python"]
    assert isinstance(body["runtime_dependencies"], dict)
    assert isinstance(body["live_server_reachable"], bool)


def test_unknown_tool_is_a_named_jsonrpc_error():
    resp = mcp.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "accountable-surface.perceive", "arguments": {}}}
    )
    assert resp["error"]["code"] == -32602


def test_initialize_carries_identity():
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 5, "method": "initialize"})
    info = resp["result"]["serverInfo"]
    assert info["name"] == "accountable-surface"
    assert info["version"] == __version__


def test_notification_without_id_gets_no_response():
    assert mcp.handle_request({"jsonrpc": "2.0", "method": "initialized"}) is None


def test_serve_round_trips_over_stdio():
    requests = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "accountable-surface.status"}}),
    ]) + "\n"
    out = io.StringIO()
    rc = mcp.serve(io.StringIO(requests), out)
    assert rc == 0
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 2
    listed = json.loads(lines[0])["result"]["tools"]
    assert {t["name"] for t in listed} == {
        "accountable-surface.status", "accountable-surface.doctor"}
    status = json.loads(json.loads(lines[1])["result"]["content"][0]["text"])
    assert status["server"] == "accountable-surface"
