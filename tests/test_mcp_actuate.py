"""Actuation over MCP -- the riskiest surface in this repository, tested by trying
to cross each of the two doors that guard it.

A remote caller reaches an effector only when the operator has BOTH exposed it in
the registry and granted its action kind. The tests below take away one door at a
time and assert that nothing was written, nothing was sent, and the receipt says
plainly that nothing happened.

Nothing here touches a network. The api entry gets `FakeApiDriver` through the
registry's injection point and a fake token on the environment for one test.
"""

from __future__ import annotations

import json

import pytest

from accountable_surface.api_effector import GITHUB_ISSUE_COMMENTS, FakeApiDriver
from accountable_surface.effector import FilesystemEffector
from accountable_surface.registry import (
    EffectorRegistry,
    Exposed,
    _decode_bytes,
    load_effectors,
)
from accountable_surface.remote_actuation import _receipt, actuate_impl
from accountable_surface.server import _doctor_payload
from accountable_surface.surface import AccountableSurface, ActuationOutcome

THREAD = "/repos/octo/demo/issues/7/comments"


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-actuate-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "mcp-caller"},
        "intent": "mcp actuation test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _spec(tmp_path, entries):
    path = tmp_path / "effectors.json"
    path.write_text(json.dumps({"effectors": entries}), encoding="utf-8")
    return str(path)


def _fs_registry(tmp_path):
    return load_effectors(_spec(tmp_path, [{"action_kind": "fs.write", "type": "filesystem",
                                            "root": str(tmp_path)}]))


# --- what the operator exposed ----------------------------------------------


def test_nothing_is_exposed_until_the_operator_names_a_file(monkeypatch):
    """A fresh install actuates nothing. The capability layer starts empty and the
    reason is carried, so silence is never mistaken for a deliberate empty set."""
    monkeypatch.delenv("ACCOUNTABLE_SURFACE_EFFECTORS", raising=False)
    registry = load_effectors()
    assert registry.action_kinds() == []
    assert "nothing is exposed" in registry.refusals()[0]


def test_an_unreadable_spec_exposes_nothing_and_says_why(tmp_path):
    registry = load_effectors(str(tmp_path / "absent.json"))
    assert len(registry) == 0
    assert "unreadable" in registry.refusals()[0]


def test_a_command_effector_is_refused_by_name(tmp_path):
    """`command` is a documented null, not an oversight. The refusal names the type
    and the reason, so an operator reading `doctor` sees a decision."""
    registry = load_effectors(_spec(tmp_path, [{"action_kind": "os.run", "type": "command",
                                                "cwd": str(tmp_path)}]))
    assert registry.action_kinds() == []
    assert "deliberately not exposed" in registry.refusals()[0]
    assert "runs a program" in registry.refusals()[0]


def test_an_unknown_type_is_refused_and_the_exposable_ones_are_named(tmp_path):
    registry = load_effectors(_spec(tmp_path, [{"action_kind": "fs.write", "type": "sqlite"}]))
    assert len(registry) == 0
    assert "'api', 'filesystem'" in registry.refusals()[0]


def test_an_action_kind_the_entry_cannot_serve_is_refused(tmp_path):
    """The key is the caller's whole address for a capability. If a filesystem entry
    could be filed under `api.post`, the registry would be a rename tool."""
    registry = load_effectors(_spec(tmp_path, [{"action_kind": "api.post", "type": "filesystem",
                                                "root": str(tmp_path)}]))
    assert registry.action_kinds() == []
    assert "is not one this effector serves" in registry.refusals()[0]


def test_a_second_entry_for_the_same_action_kind_does_not_replace_the_first(tmp_path):
    wide = tmp_path / "wide"
    narrow = tmp_path / "wide" / "narrow"
    narrow.mkdir(parents=True)
    registry = load_effectors(_spec(tmp_path, [
        {"action_kind": "fs.write", "type": "filesystem", "root": str(narrow)},
        {"action_kind": "fs.write", "type": "filesystem", "root": str(wide)},
    ]))
    assert registry.get("fs.write").describe.endswith(narrow.resolve().as_posix())
    assert "the first entry stands" in registry.refusals()[0]


# --- the two doors -----------------------------------------------------------


def test_an_unexposed_action_kind_is_refused_before_a_grant_is_read(tmp_path):
    """The registry is checked first, so a caller cannot make the server consult its
    grants (and journal the attempt) for a capability that was never exposed."""
    surface = AccountableSurface()
    out = actuate_impl(surface, [_grant(["api.post"])], _fs_registry(tmp_path),
                       "api.post", THREAD, '{"intent": "post_comment", "body": {}}')
    assert out["decision"] == "deny"
    assert out["acted"] is False
    assert out["journal_entry"] is None
    assert out["exposed_action_kinds"] == ["fs.write"]
    assert surface.journal == []


def test_an_exposed_effector_with_no_grant_writes_nothing(tmp_path):
    target = tmp_path / "note.txt"
    out = actuate_impl(AccountableSurface(), [], _fs_registry(tmp_path),
                       "fs.write", str(target), "hello")
    assert out["decision"] == "deny"
    assert "cannot self-authorize" in out["reasons"][0]
    assert not target.exists()


def test_a_grant_for_another_action_does_not_reach_this_one(tmp_path):
    target = tmp_path / "note.txt"
    out = actuate_impl(AccountableSurface(), [_grant(["summarize"])], _fs_registry(tmp_path),
                       "fs.write", str(target), "hello")
    assert out["decision"] == "deny"
    assert not target.exists()


def test_the_grant_that_runs_is_the_one_naming_this_action(tmp_path):
    """An operator holding several grants is the normal case. The call has to find
    the grant for its own action kind rather than whichever was loaded first, or an
    unrelated grant would decide every action's fate."""
    target = tmp_path / "note.txt"
    grants = [_grant(["summarize"]), _grant(["fs.write"])]
    out = actuate_impl(AccountableSurface(), grants, _fs_registry(tmp_path),
                       "fs.write", str(target), "hello")
    assert out["decision"] == "allow"
    assert target.read_text(encoding="utf-8") == "hello"


def test_a_granted_write_lands_and_verifies(tmp_path):
    target = tmp_path / "note.txt"
    out = actuate_impl(AccountableSurface(), [_grant(["fs.write"])], _fs_registry(tmp_path),
                       "fs.write", str(target), "hello")
    assert out["decision"] == "allow"
    assert out["acted"] is True
    assert out["verified"] is True
    assert target.read_text(encoding="utf-8") == "hello"


def test_a_target_outside_the_registered_root_is_refused_by_the_effector(tmp_path):
    """The grant names the action, the registry names the reach. A write one level
    above the registered root has a gate allow and still does not happen."""
    outside = tmp_path.parent / "escaped.txt"
    inner = tmp_path / "sandbox"
    inner.mkdir()
    registry = load_effectors(_spec(tmp_path, [{"action_kind": "fs.write", "type": "filesystem",
                                                "root": str(inner)}]))
    out = actuate_impl(AccountableSurface(), [_grant(["fs.write"])], registry,
                       "fs.write", str(outside), "escaped")
    assert out["acted"] is False
    assert out["verdict"] == "refused-by-effector"
    assert not outside.exists()


# --- the receipt -------------------------------------------------------------


def test_the_receipt_carries_only_this_calls_journal_entry(tmp_path):
    """The journal is the operator's record of everything. A caller gets back the
    entry for the action it just caused, and no view of anyone else's."""
    surface, registry, grants = AccountableSurface(), _fs_registry(tmp_path), [_grant(["fs.write"])]
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    actuate_impl(surface, grants, registry, "fs.write", str(first), "one")
    out = actuate_impl(surface, grants, registry, "fs.write", str(second), "two")
    entry = out["journal_entry"]
    assert entry["kind"] == "actuation"
    assert entry["detail"]["verified"] is True
    assert entry["detail"]["effector_bound"].startswith("fs:root=")
    assert second.name in entry["summary"]
    assert first.name not in json.dumps(out)  # the earlier action is the operator's to read
    assert len([e for e in surface.journal if e.kind == "actuation"]) == 2


def test_a_receipt_never_reaches_back_for_an_earlier_calls_entry(tmp_path):
    """The `since` mark is what holds the guarantee above when a call records nothing
    of its own. Drop it and the newest actuation in the journal, left there by
    whoever called last, comes back as this caller's proof of work. Every path
    through `AccountableSurface.actuate` journals today, so `_receipt` is called
    directly here: it is the only way to reach the case the mark exists for."""
    surface, registry, grants = AccountableSurface(), _fs_registry(tmp_path), [_grant(["fs.write"])]
    earlier = actuate_impl(surface, grants, registry, "fs.write", str(tmp_path / "earlier.txt"), "one")
    assert earlier["journal_entry"] is not None

    recorded_nothing = ActuationOutcome(
        acted=False, decision="deny", verified=False, verdict="not-acted", rolled_back=False,
        reasons=["nothing was recorded"], before_digest="", after_digest=None,
    )
    receipt = _receipt(surface, recorded_nothing, [], since=len(surface.journal))
    assert receipt["journal_entry"] is None
    assert "earlier.txt" not in json.dumps(receipt)


def test_a_write_that_did_not_land_reports_acted_without_verified(tmp_path):
    """False-success control for this layer. The effector writes something other than
    the authorized bytes, so `acted` is true and the write is real. A caller reading
    `acted` alone would call that a success; the receipt refuses to, and the surface
    rolls the write back."""

    class _DriftingEffector(FilesystemEffector):
        def _write(self, path, content):
            path.write_bytes(content + b" (drifted)")

    effector = _DriftingEffector(tmp_path)
    registry = EffectorRegistry({"fs.write": Exposed("fs.write", effector, _decode_bytes, "test")}, [])
    target = tmp_path / "note.txt"
    out = actuate_impl(AccountableSurface(), [_grant(["fs.write"])], registry,
                       "fs.write", str(target), "hello")
    assert out["acted"] is True
    assert out["verified"] is False
    assert out["rolled_back"] is True
    assert out["certificate"]["verdict"] == "refuted"
    assert not target.exists()


def test_when_two_grants_name_the_action_the_receipt_says_which_was_used(tmp_path):
    """Honest null, stated in the receipt: the first matching grant is the one that
    runs, so a caller is never silently reaching under a grant it cannot see."""
    grants = [_grant(["fs.write"]), _grant(["fs.write", "os.run"])]
    out = actuate_impl(AccountableSurface(), grants, _fs_registry(tmp_path),
                       "fs.write", str(tmp_path / "note.txt"), "hello")
    assert out["decision"] == "allow"
    assert "2 grants name 'fs.write'; the first one was used" in out["reasons"]


# --- the api path ------------------------------------------------------------


def _api_registry(tmp_path, driver):
    return load_effectors(_spec(tmp_path, [{"action_kind": "api.post", "type": "api",
                                            "service": "github"}]), api_driver=driver)


def test_a_granted_api_post_travels_through_the_registry(tmp_path, monkeypatch):
    monkeypatch.setenv(GITHUB_ISSUE_COMMENTS.auth_env, "fake-token-for-tests-only")
    driver = FakeApiDriver({THREAD: []})
    out = actuate_impl(AccountableSurface(), [_grant(["api.post"])], _api_registry(tmp_path, driver),
                       "api.post", THREAD, '{"intent": "post_comment", "body": {"body": "hello"}}')
    assert out["decision"] == "allow"
    assert out["verified"] is True
    assert [m["body"] for m in driver._collections[THREAD]] == ["hello"]


@pytest.mark.parametrize("content", ["not json at all", '["intent"]', '{"body": {}}',
                                     '{"intent": "post_comment", "body": "hello"}'])
def test_content_that_is_not_an_intent_and_body_never_reaches_the_driver(tmp_path, monkeypatch, content):
    monkeypatch.setenv(GITHUB_ISSUE_COMMENTS.auth_env, "fake-token-for-tests-only")
    driver = FakeApiDriver({THREAD: []})
    out = actuate_impl(AccountableSurface(), [_grant(["api.post"])], _api_registry(tmp_path, driver),
                       "api.post", THREAD, content)
    assert out["decision"] == "deny"
    assert "is not what 'api.post' accepts" in out["reasons"][0]
    assert driver.requests == []


def test_an_intent_the_service_does_not_declare_comes_back_as_a_receipt(tmp_path, monkeypatch):
    """The effector raises before a plan exists, which is a refusal and not a fault.
    A caller gets the same receipt shape as any other denial rather than a crash."""
    monkeypatch.setenv(GITHUB_ISSUE_COMMENTS.auth_env, "fake-token-for-tests-only")
    driver = FakeApiDriver({THREAD: []})
    out = actuate_impl(AccountableSurface(), [_grant(["api.post"])], _api_registry(tmp_path, driver),
                       "api.post", THREAD, '{"intent": "delete_repo", "body": {}}')
    assert out["decision"] == "deny"
    assert "is not declared by github" in out["reasons"][0]
    assert [r["method"] for r in driver.requests] == ["GET"]  # the before-read, nothing else


# --- what the server says about itself ---------------------------------------


def test_doctor_names_actuate_and_reports_an_empty_registry_by_default():
    payload = _doctor_payload()
    assert "actuate" in payload["tools"]
    assert payload["effectors"]["exposed"] == []
    assert payload["effectors"]["refused"] != []
