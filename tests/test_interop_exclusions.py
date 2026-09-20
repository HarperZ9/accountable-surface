"""HARD EXCLUSIONS -- asserted unreachable through the interop MCP server.

The boundary is the ``SAFE_READ_VERBS`` allowlist: the server reaches exactly the
verbs it names (today, device ls). ``EXCLUDED_CAPABILITIES`` restates the classes
that must never be reachable -- CAPTCHA solving, anti-bot stealth / fingerprint
patching, reCAPTCHA token harvest, and mass or obfuscated authenticated outreach,
plus mutating device verbs -- and these tests prove there is no argument a caller can
pass through any tool to reach one. They are refused before an effector is built or a
subprocess spawns, no tool advertises them, and the actuator runner refuses them too.
"""

from __future__ import annotations

from accountable_surface import interop_mcp as mcp
from accountable_surface.effector import RefusedActuation
from accountable_surface.interop_mcp import EXCLUDED_CAPABILITIES, EXCLUDED_VERBS
from accountable_surface.interop_runtime import (
    WIRED_ACTIONS,
    AccountableInterop,
    is_excluded,
    resolve_wired_action,
)
from accountable_surface.native_control_effector import SAFE_READ_VERBS, FakeNativeControlRunner


def _runner():
    return FakeNativeControlRunner({"ok": True, "result": {"ok": True, "entries": []}})


def _interop(tmp_path, runner):
    return AccountableInterop(
        grants=[{
            "authorization_version": "0.1", "receipt_id": "r", "kind": "authorization-grant",
            "principal": {"id": "op", "role": "operator"}, "agent": {"id": "a"}, "intent": "t",
            "scope": {"allowed_actions": list(WIRED_ACTIONS) + [f"native.{d}.{v}" for d, v in EXCLUDED_VERBS],
                      "allowed_targets": []},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00",
            "revoked": False,
        }],
        receipt_path=str(tmp_path / "receipts.jsonl"),
        runner_factory=lambda d, v: runner,
        clock=lambda: "2026-09-19T00:00:00+00:00",
    )


def test_all_named_exclusion_classes_are_present():
    assert set(EXCLUDED_CAPABILITIES) == {
        "captcha_solving", "anti_bot_stealth", "token_harvest", "mass_outreach", "mutating_device"}
    # every class is non-empty -- the denylist is not a hollow label.
    assert all(pairs for pairs in EXCLUDED_CAPABILITIES.values())


def test_excluded_verbs_are_disjoint_from_the_safe_allowlist():
    assert EXCLUDED_VERBS.isdisjoint(SAFE_READ_VERBS)
    for domain, verb in EXCLUDED_VERBS:
        assert is_excluded(domain, verb) is True
        assert (domain, verb) not in SAFE_READ_VERBS


def test_resolve_refuses_every_excluded_action_kind():
    for domain, verb in EXCLUDED_VERBS:
        try:
            resolve_wired_action(f"native.{domain}.{verb}")
            raise AssertionError(f"native.{domain}.{verb} must be refused")
        except RefusedActuation:
            pass


def test_actuate_refuses_excluded_verbs_and_spawns_nothing(tmp_path):
    """Even with a (deliberately over-broad) grant naming the excluded action kinds,
    the server refuses them before building an effector or calling the actuator."""
    runner = _runner()
    interop = _interop(tmp_path, runner)
    for domain, verb in EXCLUDED_VERBS:
        out = interop.actuate(f"native.{domain}.{verb}", str(tmp_path))
        assert out["decision"] == "deny"
        assert out["verdict"] == "refused-before-actuation"
        assert out["acted"] is False
    assert runner.calls == []  # not one excluded verb reached the actuator


def test_raw_mutating_device_verbs_are_not_wired(tmp_path):
    runner = _runner()
    interop = _interop(tmp_path, runner)
    for action_kind in ("device.exec", "device.write", "native.device.exec", "native.device.write"):
        out = interop.actuate(action_kind, str(tmp_path))
        assert out["acted"] is False and out["decision"] == "deny"
    assert runner.calls == []


def test_no_advertised_tool_maps_to_an_excluded_capability():
    names = " ".join(t["name"] for t in mcp._tool_defs())
    for token in ("captcha", "recaptcha", "token", "stealth", "fingerprint", "behave",
                  "autofill", "linkedin", "send_bulk", "exec", "write", "scrape", "targets"):
        assert token not in names
    # the only actuation tools are the read-only actuate + device_ls.
    assert "accountable-surface.device_ls" in names
    assert "accountable-surface.actuate" in names


def test_device_ls_only_ever_reaches_device_ls(tmp_path):
    (tmp_path / "d").mkdir()
    runner = _runner()
    interop = _interop(tmp_path, runner)
    interop.device_ls(str(tmp_path / "d"))
    assert all(call[:2] == ("device", "ls") for call in runner.calls)


def test_actuator_runner_refuses_excluded_verbs_directly():
    runner = _runner()
    for domain, verb in EXCLUDED_VERBS:
        try:
            runner.run(domain, verb, ["x"])
            raise AssertionError(f"{domain}.{verb} must be refused by the runner")
        except RefusedActuation:
            pass


def test_unwired_but_safe_looking_verb_is_still_refused(tmp_path):
    """A verb in the effector's SAFE_READ_VERBS_TARGET set (e.g. device read) is NOT
    yet wired here, so the server refuses it -- target is not the same as shipped."""
    runner = _runner()
    interop = _interop(tmp_path, runner)
    out = interop.actuate("native.device.read", str(tmp_path))
    assert out["acted"] is False and out["decision"] == "deny"
    assert runner.calls == []
