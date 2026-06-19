"""Tests for OS actuation — CommandEffector (Phase 5, third effector).

Offline + deterministic via a FakeRunner (no real subprocess). Proves: inert until
authorized; bounded to an allowlist; and — the headline — commands are IRREVERSIBLE,
so the surface escalates to needs-human unless the grant explicitly pre-authorizes it.
"""

from __future__ import annotations

import pytest

from accountable_surface.effector import RefusedActuation
from accountable_surface.os_effector import CommandEffector
from accountable_surface.surface import AccountableSurface


class _Allow:
    decision = "allow"

    def __init__(self, action_kind, target):
        self.request = {"planned_action": {"action_kind": action_kind, "target": target}}


class _FakeRunner:
    def __init__(self, exit_code=0):
        self.calls = []
        self._exit = exit_code

    def run(self, argv, cwd):
        self.calls.append((list(argv), cwd))
        return {"exit_code": self._exit, "stdout": "ok", "stderr": ""}


def _grant(actions, *, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-os-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "os-agent"},
        "intent": "os run test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_run_without_allow_refuses(tmp_path):
    runner = _FakeRunner()
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    plan = eff.preview("greet", ["echo", "hi"])
    with pytest.raises(RefusedActuation):
        eff.act(plan, allow_receipt=None, command=["echo", "hi"])
    assert runner.calls == []  # nothing ran


def test_run_non_allowlisted_refuses(tmp_path):
    runner = _FakeRunner()
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    plan = eff.preview("danger", ["rm", "-rf", "/"])
    with pytest.raises(RefusedActuation):
        eff.act(plan, _Allow("os.run", "danger"), command=["rm", "-rf", "/"])
    assert runner.calls == []  # the bound holds even with an allow receipt


def test_run_with_allow_runs_and_verifies(tmp_path):
    runner = _FakeRunner(exit_code=0)
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    plan = eff.preview("greet", ["echo", "hi"])
    after = eff.act(plan, _Allow("os.run", "greet"), command=["echo", "hi"])
    assert runner.calls[0][0] == ["echo", "hi"]
    assert eff.verify(plan, after).status == "pass"


def test_failed_command_fails_verification(tmp_path):
    runner = _FakeRunner(exit_code=1)
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    plan = eff.preview("greet", ["echo", "hi"])
    after = eff.act(plan, _Allow("os.run", "greet"), command=["echo", "hi"])
    assert eff.verify(plan, after).status == "failed"


def test_selftest_holds(tmp_path):
    assert CommandEffector(_FakeRunner(), {"echo"}, tmp_path).selftest() is True


# --- the irreversible -> needs-human escalation, via actuate --------------

def test_actuate_no_grant_does_not_run(tmp_path):
    runner = _FakeRunner()
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    out = AccountableSurface().actuate(eff, target="greet", content=["echo", "hi"], authorization={})
    assert out.acted is False
    assert out.decision == "deny"
    assert runner.calls == []


def test_actuate_irreversible_without_permission_escalates(tmp_path):
    # The gate would allow it, but the action is irreversible and the grant does NOT
    # pre-authorize irreversibility -> escalate to needs-human; nothing runs.
    runner = _FakeRunner()
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    out = AccountableSurface().actuate(eff, target="greet", content=["echo", "hi"], authorization=_grant(["os.run"]))
    assert out.acted is False
    assert out.decision == "needs-human"
    assert "irreversible" in out.verdict
    assert runner.calls == []


def test_actuate_irreversible_with_permission_runs(tmp_path):
    runner = _FakeRunner(exit_code=0)
    eff = CommandEffector(runner, {"echo"}, tmp_path)
    out = AccountableSurface().actuate(
        eff, target="greet", content=["echo", "hi"], authorization=_grant(["os.run"]), allow_irreversible=True
    )
    assert out.acted is True
    assert out.verified is True
    assert runner.calls[0][0] == ["echo", "hi"]
