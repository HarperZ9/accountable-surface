"""The plugin profile's pipeline tools, end to end through the interop server.

Each write tool runs one step through the whole pipeline (policy, gate, act,
readback, verdict, receipt) and returns the verdict, the policy outcome with
every rule and reason, and the receipt reference. By default the tools are not
exposed: the registry refuses the web effector by name, so a call returns that
refusal and reaches nothing. The tests below expose them on purpose, to a
pipeline on a local 127.0.0.1 fixture site.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from actuation_site import Site
from actuation_world import PASSWORD, Console, World

from accountable_surface import authority_cli, interop_mcp, pipeline_tools


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


@pytest.fixture
def world(tmp_path, site, monkeypatch):
    w = World(tmp_path, site)
    tools = pipeline_tools.PipelineTools(w.pipe, w.store, w.receipts, w.evidence)
    monkeypatch.setattr(pipeline_tools, "current", lambda: tools)
    return w


def call(name, args=None):
    resp = interop_mcp.handle_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                       "params": {"name": name, "arguments": args or {}}}, profile="plugin")
    result = resp["result"]
    text = result["content"][0]["text"]
    try:
        return json.loads(text), result["isError"], text
    except ValueError:
        return {"text": text}, result["isError"], text


def rules(payload):
    return {h["rule"] for h in payload["policy"]["rule_hits"]}


SUBMIT = {"control": {"name": "Submit order", "role": "button"}, "action": "/order/submit",
          "expect_title": "Order received",
          "post_condition": {"kind": "text_present", "path": "/orders", "value": "Order 1: quantity 1"}}


def submit_args(site):
    return {"origin": site.origin, "path": "/order", **SUBMIT}


def test_write_tools_are_not_exposed_by_default(site):
    payload, is_error, _ = call("browser_navigate", {"origin": site.origin, "path": "/notes"})
    assert is_error and payload["exposed"] is False and "web" in payload["error"]
    assert site.requests == []


def test_navigate_acts_verifies_and_names_its_receipt(world, site):
    payload, is_error, _ = call("browser_navigate", {"origin": site.origin, "path": "/notes"})
    assert not is_error and (payload["status"], payload["verdict"]) == ("acted", "verified")
    assert payload["receipt"]["seq"] == 1 and payload["receipt"]["hash"]
    assert payload["policy"]["outcome"] == "pass"


def test_a_password_fill_is_refused_with_its_rule_and_the_value_never_returns(world, site):
    call("browser_navigate", {"origin": site.origin, "path": "/login"})
    payload, is_error, text = call("browser_fill", {"origin": site.origin, "path": "/login",
                                                    "control": {"name": "Password"}, "value": PASSWORD})
    assert payload["status"] == "refused" and "R4.secret-field" in rules(payload)
    assert PASSWORD not in text and world.driver.field_value("Password") == ""


def test_a_captcha_page_stops_the_tool_and_pauses_the_origin(world, site):
    world.driver.navigate(site.url("/captcha"))
    payload, _, text = call("browser_fill", {"origin": site.origin, "path": "/captcha",
                                             "control": {"name": "Email"}, "value": "ada@example.test"})
    assert payload["status"] == "stopped" and "R3.challenge" in rules(payload)
    assert "human check" in payload["message"] and world.store.paused_targets() == frozenset({site.origin})


def test_submit_is_held_and_no_token_crosses_the_boundary(world, site):
    call("browser_navigate", {"origin": site.origin, "path": "/order"})
    held, _, held_text = call("browser_submit", submit_args(site))
    assert held["status"] == "needs-human" and held["approval_id"] and site.orders == []
    assert "accountable-surface-authority approve" in held["message"]
    pending, _, pending_text = call("approvals_pending")
    assert [p["approval_id"] for p in pending["pending"]] == [held["approval_id"]]
    assert "command" in pending["pending"][0] and "token" not in pending["pending"][0]
    authority_cli.main(["approve", "--state", str(world.store.path), "--approval-id", held["approval_id"]],
                       console=Console("submit", site.origin.split("//")[1]))
    done, _, done_text = call("browser_submit", submit_args(site))
    assert (done["status"], done["verdict"]) == ("acted", "verified") and len(site.orders) == 1
    with sqlite3.connect(world.store.path) as conn:
        secrets = [v for row in conn.execute("SELECT token, nonce FROM approvals") for v in row if v]
    assert secrets and not any(s in t for s in secrets for t in (held_text, pending_text, done_text))


def test_withdraw_cancels_a_pending_request_and_cannot_approve(world, site):
    call("browser_navigate", {"origin": site.origin, "path": "/order"})
    held, _, _ = call("browser_submit", submit_args(site))
    payload, is_error, _ = call("withdraw_approval", {"approval_id": held["approval_id"]})
    assert not is_error and payload["withdrawn"] is True
    assert call("approvals_pending")[0]["pending"] == []
    with pytest.raises(SystemExit):
        authority_cli.main(["approve", "--state", str(world.store.path), "--approval-id", held["approval_id"]],
                           console=Console("submit", site.origin.split("//")[1]))
    assert call("browser_submit", submit_args(site))[0]["status"] == "needs-human"
    assert site.orders == []


def test_check_plan_is_advisory(world, site):
    call("browser_navigate", {"origin": site.origin, "path": "/order"})
    calls, lines = list(world.driver.mutating), len(world.receipt_lines())
    step = {"step_id": "s1", "action_kind": "web.submit", "target": {"origin": site.origin, "path": "/order",
            "control": SUBMIT["control"]}, "args": {"action": "/order/submit", "expect_title": "Order received"},
            "post_condition": SUBMIT["post_condition"]}
    payload, is_error, _ = call("check_plan", {"plan": step})
    assert not is_error and payload["steps"][0]["outcome"] == "confirm"
    assert "R7.irreversible" in {h["rule"] for h in payload["steps"][0]["rule_hits"]}
    assert world.driver.mutating == calls and world.store.pending() == []
    assert len(world.receipt_lines()) == lines and site.orders == []


def test_run_plan_through_the_tool(world, site):
    plan = {"schema": "accountable-surface.action-plan/v1", "plan_id": "p1", "steps": [
        {"step_id": "s1", "action_kind": "web.navigate", "target": {"origin": site.origin, "path": "/notes"},
         "post_condition": {"kind": "url_is", "value": site.url("/notes")}},
        {"step_id": "s2", "action_kind": "web.fill",
         "target": {"origin": site.origin, "path": "/notes", "control": {"name": "Title"}}, "args": {"value": "x"},
         "post_condition": {"kind": "field_value_is", "control": {"name": "Title"}, "value": "x"}}]}
    payload, is_error, _ = call("run_plan", {"plan": plan})
    assert not is_error and [s["verdict"] for s in payload["steps"]] == ["verified", "verified"]
    assert payload["certificate"]["verdict"] == "verified" and payload["not_run"] == []


def test_receipt_verify_through_the_tool(world, site):
    call("browser_navigate", {"origin": site.origin, "path": "/notes"})
    payload, is_error, _ = call("receipt_verify", {"level": "verdict"})
    assert not is_error and payload["verdict"] == "MATCH"


@pytest.mark.parametrize("extra", [{"grant": {"scope": {}}}, {"allow_irreversible": True}, {"tier": "full"}])
def test_an_argument_outside_the_schema_is_refused(world, site, extra):
    payload, is_error, _ = call("browser_navigate", {"origin": site.origin, "path": "/notes", **extra})
    assert is_error and "unexpected argument" in payload["error"] and site.requests == []


def test_a_submit_whose_response_the_effector_cannot_confirm_is_not_verified(world, site):
    """No expected response title: the order lands, the separate read sees it, and
    the effector's own check cannot confirm the response, so the meet is drift."""
    call("browser_navigate", {"origin": site.origin, "path": "/order"})
    args = {k: v for k, v in submit_args(site).items() if k != "expect_title"}
    held = call("browser_submit", args)[0]
    authority_cli.main(["approve", "--state", str(world.store.path), "--approval-id", held["approval_id"]],
                       console=Console("submit", site.origin.split("//")[1]))
    done = call("browser_submit", args)[0]
    assert done["status"] == "acted" and done["verdict"] == "drift" and len(site.orders) == 1
