"""The interop MCP stdio server -- protocol framing plus the runtime it carries.

The protocol layer (accountable_surface.interop_mcp) is stdlib-only JSON-RPC over
stdio: initialize, tools/list, tools/call, notifications, and the health tools answer
with no runtime. The runtime layer (accountable_surface.interop_runtime) carries the
six accountable primitives and the one shipped read-only verb, device ls, and is
exercised offline with a FakeNativeControlRunner so the whole loop -- gate, act,
independent verify, journal, receipt -- is proven without spawning Node.
"""

from __future__ import annotations

import io
import json
import os

import accountable_surface.interop_runtime as rt
from accountable_surface import __version__
from accountable_surface import interop_mcp as mcp
from accountable_surface.interop_runtime import AccountableInterop
from accountable_surface.native_control_effector import FakeNativeControlRunner


def _grant(actions):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-interop-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "interop-agent"},
        "intent": "interop device-ls test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": []},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _fixture_dir(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    return tmp_path


def _entries_from_disk(path):
    return [{"name": e.name, "type": "dir" if e.is_dir() else "file", "kb": 0} for e in os.scandir(path)]


def _receipt(entries, ok=True):
    return {"schema": "project-telos.native-control/v1", "action": "device.ls", "target": ".",
            "ok": ok, "result": {"ok": ok, "path": ".", "entries": entries, "count": len(entries)},
            "at": "2026-09-19T00:00:00Z"}


def _interop(tmp_path, actions=("native.device.ls",), understate=None):
    fixture = _fixture_dir(tmp_path / "dir")
    entries = _entries_from_disk(fixture)
    if understate is not None:
        entries = [e for e in entries if e["name"] != understate]
    runner = FakeNativeControlRunner(_receipt(entries))
    interop = AccountableInterop(
        grants=[_grant(actions)] if actions else [],
        receipt_path=str(tmp_path / "receipts.jsonl"),
        runner_factory=lambda d, v: runner,
        clock=lambda: "2026-09-19T00:00:00+00:00",
    )
    return interop, runner, fixture


# --- protocol layer (stdlib only) --------------------------------------------

def test_initialize_carries_identity():
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    info = resp["result"]["serverInfo"]
    assert info["name"] == "accountable-surface"
    assert info["version"] == __version__
    assert resp["result"]["protocolVersion"] == mcp.MCP_PROTOCOL_VERSION


def test_tools_list_advertises_every_tool():
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {
        "accountable-surface.perceive", "accountable-surface.propose",
        "accountable-surface.actuate", "accountable-surface.device_ls",
        "accountable-surface.journal", "accountable-surface.receipt",
        "accountable-surface.status", "accountable-surface.doctor",
    }


def test_status_admits_runtime_and_maps_the_six_primitives():
    body = mcp.status_payload()
    assert body["admits_runtime"] is True and body["transport"] == "stdio"
    assert set(body["primitives"]) == {"perceive", "propose", "gate", "actuate", "journal", "receipt"}
    # "gate" is the decision propose returns -- it maps to the propose tool.
    assert body["primitives"]["gate"] == body["primitives"]["propose"] == "accountable-surface.propose"


def test_doctor_reports_the_hard_exclusions():
    body = mcp.doctor_payload()
    assert set(body["excluded_capabilities"]) == {
        "captcha_solving", "anti_bot_stealth", "token_harvest", "mass_outreach", "mutating_device"}
    assert body["runtime_reachable"] is True  # siblings are installed in CI/dev
    assert "device.ls" in body["runtime"]["safe_read_verbs"]


def test_notification_without_id_gets_no_response():
    assert mcp.handle_request({"jsonrpc": "2.0", "method": "initialized"}) is None


def test_unknown_tool_is_a_named_error():
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                               "params": {"name": "accountable-surface.captcha", "arguments": {}}})
    assert resp["error"]["code"] == -32602


# --- runtime layer: the six primitives + device ls --------------------------

def test_perceive_directory_is_an_independent_witness(tmp_path):
    interop, _runner, fixture = _interop(tmp_path)
    observed = interop.perceive(str(fixture))
    assert observed["data"]["exists"] is True
    assert observed["data"]["count"] == 3  # a.txt, b.txt, sub
    assert observed["organ"] == "native-control-list-effector"


def test_propose_default_denies_without_a_grant(tmp_path):
    interop, _runner, fixture = _interop(tmp_path, actions=())
    decision = interop.propose("native.device.ls", str(fixture))
    assert decision["decision"] == "deny" and decision["gate"] == "deny"


def test_propose_allows_under_a_matching_grant(tmp_path):
    interop, _runner, fixture = _interop(tmp_path)
    decision = interop.propose("native.device.ls", str(fixture))
    assert decision["decision"] == "allow" and decision["gate"] == "allow"


def test_device_ls_acts_verifies_journals_and_receipts(tmp_path):
    interop, runner, fixture = _interop(tmp_path)
    out = interop.device_ls(str(fixture))
    assert out["acted"] is True and out["decision"] == "allow" and out["verified"] is True
    assert out["verdict"] == "pass"
    assert out["receipt"]["verdict"] == "MATCH"
    assert out["journal_entry"] is not None and out["journal_entry"]["kind"] == "actuation"
    assert len(runner.calls) == 1 and runner.calls[0][:2] == ("device", "ls")


def test_device_ls_default_deny_reaches_no_actuator(tmp_path):
    interop, runner, fixture = _interop(tmp_path, actions=())
    out = interop.device_ls(str(fixture))
    assert out["acted"] is False and out["decision"] == "deny"
    assert runner.calls == []  # default-deny reached no subprocess


def test_drifting_actuator_is_caught_and_receipt_records_drift(tmp_path):
    """False-success control at the server boundary: the actuator under-reports a real
    entry, the surface's independent witness disagrees, verify fails, and the receipt
    honestly records DRIFT while its own chain still re-derives to MATCH."""
    interop, _runner, fixture = _interop(tmp_path, understate="b.txt")
    out = interop.device_ls(str(fixture))
    assert out["acted"] is True and out["verified"] is False
    assert out["rolled_back"] is True
    assert out["receipt"]["verdict"] == "DRIFT"
    assert interop.receipt()["label"] == "MATCH"  # the store is honest about the bad action


def test_receipt_rederives_then_drifts_on_tamper(tmp_path):
    interop, _runner, fixture = _interop(tmp_path)
    interop.device_ls(str(fixture))
    assert interop.receipt()["label"] == "MATCH"
    store = tmp_path / "receipts.jsonl"
    store.write_text(store.read_text(encoding="utf-8").replace('"MATCH"', '"MATCH_"'), encoding="utf-8")
    assert interop.receipt()["label"] == "DRIFT"


def test_journal_reads_entries_with_a_chain_verdict(tmp_path):
    interop, _runner, fixture = _interop(tmp_path)
    interop.device_ls(str(fixture))
    journal = interop.journal()
    assert journal["chain_ok"] is True
    assert any(entry["kind"] == "actuation" for entry in journal["entries"])


# --- full dispatch through the protocol --------------------------------------

def test_tools_call_round_trips_device_ls_through_the_protocol(tmp_path, monkeypatch):
    interop, runner, fixture = _interop(tmp_path)
    monkeypatch.setattr(rt, "_DEFAULT", interop)
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                               "params": {"name": "accountable-surface.device_ls",
                                          "arguments": {"path": str(fixture)}}})
    assert resp["result"]["isError"] is False
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["acted"] is True and body["receipt"]["verdict"] == "MATCH"
    assert runner.calls[0][:2] == ("device", "ls")


def test_serve_round_trips_status_over_stdio():
    requests = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "accountable-surface.status"}}),
    ]) + "\n"
    out = io.StringIO()
    assert mcp.serve(io.StringIO(requests), out) == 0
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 2
    status = json.loads(json.loads(lines[1])["result"]["content"][0]["text"])
    assert status["server"] == "accountable-surface" and status["admits_runtime"] is True
