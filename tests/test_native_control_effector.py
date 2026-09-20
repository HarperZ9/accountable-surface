"""Tests for the native-control bridge effector -- the cross-language actuation seam.

Offline and deterministic: a FakeNativeControlRunner stands in for the Node subprocess,
so the accountability logic (gate -> act -> re-perceive -> verify -> journal) is proven
without spawning anything. The load-bearing check is the INDEPENDENT-WITNESS verify:
when the actuator's listing disagrees with the surface's own `os.scandir`, verify must
catch it (false-success control). The live subprocess seam is proven in
test_native_control_live.py.
"""

from __future__ import annotations

import os

from accountable_surface.effector import RefusedActuation
from accountable_surface.native_control_effector import (
    SAFE_READ_VERBS,
    FakeNativeControlRunner,
    NativeControlListEffector,
    NativeControlWriteEffector,
)
from accountable_surface.surface import AccountableSurface


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-nc-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "nc-agent"},
        "intent": "native-control read test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
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
    return {
        "schema": "project-telos.native-control/v1",
        "tool": "telos.native.control",
        "action": "device.ls",
        "target": ".",
        "ok": ok,
        "result": {"ok": ok, "path": ".", "entries": entries, "count": len(entries)},
        "background": True,
        "at": "2026-09-19T00:00:00Z",
    }


def test_no_grant_does_not_run(tmp_path):
    fixture = _fixture_dir(tmp_path)
    runner = FakeNativeControlRunner(_receipt(_entries_from_disk(fixture)))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    out = AccountableSurface().actuate(eff, target=str(fixture), content=[str(fixture)], authorization={})
    assert out.acted is False
    assert out.decision == "deny"
    assert runner.calls == []  # default-deny reached NO subprocess


def test_authorized_list_acts_verifies_matches(tmp_path):
    fixture = _fixture_dir(tmp_path)
    runner = FakeNativeControlRunner(_receipt(_entries_from_disk(fixture)))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    out = AccountableSurface().actuate(
        eff, target=str(fixture), content=[str(fixture)], authorization=_grant(["native.device.ls"])
    )
    assert out.acted is True
    assert out.decision == "allow"
    assert out.verified is True
    assert out.certificate["verdict"] == "verified"
    assert len(runner.calls) == 1 and runner.calls[0][:2] == ("device", "ls")


def test_actuator_underreport_is_caught_and_rolled_back(tmp_path):
    """False-success control: the actuator reports a listing that omits a real entry.
    The surface's independent witness (os.scandir) must catch the mismatch, so verify
    is NOT a pass -- a lying or broken actuator cannot launder a green verdict."""
    fixture = _fixture_dir(tmp_path)
    truthful = _entries_from_disk(fixture)
    understated = [e for e in truthful if e["name"] != "b.txt"]  # drop a real entry
    runner = FakeNativeControlRunner(_receipt(understated))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    out = AccountableSurface().actuate(
        eff, target=str(fixture), content=[str(fixture)], authorization=_grant(["native.device.ls"])
    )
    assert out.acted is True
    assert out.verified is False   # independent witness disagreed with the actuator
    assert out.rolled_back is True
    assert out.certificate["verdict"] == "refuted"


def test_actuator_error_verifies_failed(tmp_path):
    fixture = _fixture_dir(tmp_path)
    runner = FakeNativeControlRunner(_receipt([], ok=False))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    out = AccountableSurface().actuate(
        eff, target=str(fixture), content=[str(fixture)], authorization=_grant(["native.device.ls"])
    )
    assert out.acted is True
    assert out.verified is False


def test_unauthorized_action_kind_denied(tmp_path):
    fixture = _fixture_dir(tmp_path)
    runner = FakeNativeControlRunner(_receipt(_entries_from_disk(fixture)))
    eff = NativeControlListEffector(runner, allowed_root=fixture)
    out = AccountableSurface().actuate(
        eff, target=str(fixture), content=[str(fixture)], authorization=_grant(["fs.write"])
    )
    assert out.acted is False
    assert out.decision == "deny"
    assert runner.calls == []


def test_target_outside_bound_refused(tmp_path):
    inside = _fixture_dir(tmp_path / "inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    runner = FakeNativeControlRunner(_receipt(_entries_from_disk(outside)))
    eff = NativeControlListEffector(runner, allowed_root=inside)
    out = AccountableSurface().actuate(
        eff, target=str(outside), content=[str(outside)], authorization=_grant(["native.device.ls"])
    )
    assert out.acted is False
    assert out.verdict == "refused-by-effector"
    assert runner.calls == []  # the bound refused before the subprocess


def test_selftest_is_falsifiable():
    assert NativeControlListEffector.selftest(
        NativeControlListEffector(FakeNativeControlRunner(_receipt([])), allowed_root=".")
    ) is True


def test_runner_refuses_verbs_outside_the_safe_allowlist():
    runner = FakeNativeControlRunner(_receipt([]))
    for domain, verb in [("device", "exec"), ("device", "write"), ("browser", "send"),
                         ("browser", "captcha"), ("browser", "token"), ("browser", "linkedin"),
                         ("browser", "targets"), ("browser", "autofill")]:
        try:
            runner.run(domain, verb, ["x"])
            raise AssertionError(f"{domain}.{verb} should be refused")
        except RefusedActuation:
            pass


def test_safe_allowlist_excludes_evasion_and_mass_outreach():
    for pair in [("device", "exec"), ("device", "write"), ("browser", "captcha"),
                 ("browser", "behave"), ("browser", "token"), ("browser", "send"),
                 ("browser", "linkedin"), ("browser", "targets"), ("browser", "autofill")]:
        assert pair not in SAFE_READ_VERBS


def test_constructing_effector_for_unsafe_verb_raises():
    try:
        NativeControlListEffector(FakeNativeControlRunner(_receipt([])), allowed_root=".", verb="exec")
        raise AssertionError("device.exec must not construct a wired effector")
    except ValueError:
        pass


def test_write_effector_refuses_directly_and_escalates_through_surface(tmp_path):
    eff = NativeControlWriteEffector(allowed_root=tmp_path)
    plan = eff.preview(str(tmp_path / "t"), {"verb": "type", "text": "x"})
    try:
        eff.act(plan, allow_receipt=None, content={"verb": "type", "text": "x"})
        raise AssertionError("write-class act must refuse in this slice")
    except RefusedActuation:
        pass
    out = AccountableSurface().actuate(
        eff, target=str(tmp_path / "t"), content={"verb": "type", "text": "x"},
        authorization=_grant(["native.write"]),
    )
    assert out.acted is False
    assert out.decision == "needs-human"  # irreversible without allow_irreversible
