"""Tests for goal/task mode -- AccountableSurface.pursue (bounded autonomy).

Offline. Proves the surface executes a multi-step plan within ONE operator grant
envelope, autonomously (no per-step prompt), but halts on the first step that is
denied or fails verification -- accountability woven through every step.
"""

from __future__ import annotations

from pathlib import Path

from accountable_surface.effector import FilesystemEffector
from accountable_surface.surface import AccountableSurface, Step
from accountable_surface.web_effector import FakePageDriver, WebAction, WebEffector


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-goal-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "goal-agent"},
        "intent": "goal test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _site():
    drv = FakePageDriver(
        pages={
            "https://ok.test/": {"title": "home", "fields": {}},
            "https://ok.test/form": {"title": "form", "fields": {"Email": ""}},
        },
        start="https://ok.test/",
    )
    return WebEffector(drv, allowed_origins=["https://ok.test"]), drv


def _signup_steps(eff):
    return [
        Step(eff, "https://ok.test/", WebAction("navigate", url="https://ok.test/form")),
        Step(eff, "https://ok.test/form", WebAction("fill", url="https://ok.test/form", selector="Email", value="a@b.c")),
    ]


def test_pursue_multi_step_achieves_goal():
    eff, drv = _site()
    s = AccountableSurface()
    out = s.pursue("signup", _signup_steps(eff), authorization=_grant(["web.navigate", "web.fill"]))
    assert out.achieved is True
    assert out.steps_acted == 2
    assert drv.current_url() == "https://ok.test/form"
    assert drv.field_value("Email") == "a@b.c"  # navigate THEN fill, autonomously
    assert any(e.kind == "goal" for e in s.journal)


def test_pursue_halts_on_unauthorized_step():
    eff, drv = _site()
    s = AccountableSurface()
    out = s.pursue("signup", _signup_steps(eff), authorization=_grant(["web.navigate"]))  # no web.fill
    assert out.achieved is False
    assert out.steps_acted == 1  # navigate acted; fill denied -> halt
    assert "not acted" in out.halted_reason
    assert drv.current_url() == "https://ok.test/form"  # step 1 happened
    assert drv.field_value("Email") in (None, "")  # step 2 did not


def test_pursue_no_grant_acts_nothing():
    eff, drv = _site()
    s = AccountableSurface()
    out = s.pursue("x", _signup_steps(eff), authorization={})
    assert out.achieved is False
    assert out.steps_acted == 0
    assert drv.current_url() == "https://ok.test/"


def test_pursue_halts_on_failed_verification(tmp_path):
    class Faulty(FilesystemEffector):
        def _write(self, path, content):
            path.write_bytes(b"WRONG")

    s = AccountableSurface()
    target = str(tmp_path / "f.txt")
    Path(target).write_bytes(b"orig")
    out = s.pursue("write", [Step(Faulty(tmp_path), target, b"intended")], authorization=_grant(["fs.write"]))
    assert out.achieved is False
    assert "verif" in out.halted_reason.lower()
    assert Path(target).read_bytes() == b"orig"  # the failed step was rolled back


def test_pursue_max_steps_bounds_autonomy():
    eff, drv = _site()
    s = AccountableSurface()
    out = s.pursue(
        "signup", _signup_steps(eff), authorization=_grant(["web.navigate", "web.fill"]), max_steps=1
    )
    assert out.achieved is False
    assert out.steps_attempted == 1
    assert "budget" in out.halted_reason
