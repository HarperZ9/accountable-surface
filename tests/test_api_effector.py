"""ApiEffector -- writing through a third party's official API, accountably.

The agent hands in an intent and a body. Everything else (host, method, route,
credential) is the effector's, and each of those bounds is tested here by trying to
cross it. Nothing in this file touches a network, and the token is a fake string set
on the environment for the length of one test.
"""

from __future__ import annotations

import json

import pytest

from accountable_surface.api_effector import (
    ApiCall,
    ApiEffector,
    ApiOperation,
    ApiService,
    FakeApiDriver,
    GITHUB_ISSUE_COMMENTS,
)
from accountable_surface.credentials import MissingCredential, has_secret, require_secret
from accountable_surface.effector import RefusedActuation
from accountable_surface.surface import AccountableSurface

TOKEN = "fake-token-for-tests-only"
THREAD = "/repos/octo/demo/issues/7/comments"


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv(GITHUB_ISSUE_COMMENTS.auth_env, TOKEN)
    return TOKEN


def _grant(actions, targets=(), bounds=None):
    scope = {"allowed_actions": list(actions), "allowed_targets": list(targets)}
    if bounds is not None:
        scope["allowed_bounds"] = list(bounds)
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-api-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "remote-agent"},
        "intent": "post one comment",
        "scope": scope,
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _effector(collections=None):
    driver = FakeApiDriver(collections if collections is not None else {THREAD: []})
    return driver, ApiEffector(driver, GITHUB_ISSUE_COMMENTS)


# --- the service allowlist ---------------------------------------------------


def test_the_effector_declares_its_origin_and_its_intents():
    _, effector = _effector()
    assert effector.bound() == {"kind": "api", "origins": ["https://api.github.com"],
                                "intents": ["post_comment"]}


def test_an_intent_the_service_does_not_declare_is_refused(token):
    driver, effector = _effector()
    with pytest.raises(RefusedActuation) as exc:
        effector.preview(THREAD, ApiCall("delete_repository", {}))
    assert "not declared" in str(exc.value)
    assert driver.requests == []


def test_a_target_outside_the_intent_path_shape_is_refused(token):
    """post_comment must not reach an admin route just because the host matches."""
    driver, effector = _effector()
    with pytest.raises(RefusedActuation) as exc:
        effector.preview("/repos/octo/demo/collaborators/mallory", ApiCall("post_comment", {"body": "x"}))
    assert "path shape" in str(exc.value)
    assert driver.requests == []


def test_a_url_outside_the_service_origin_never_leaves(token):
    driver, effector = _effector()
    with pytest.raises(RefusedActuation) as exc:
        effector._send("GET", "https://evil.test/repos/octo/demo/issues/7/comments", None)
    assert "outside the service origin" in str(exc.value)
    assert driver.requests == []


# --- the gate allow ----------------------------------------------------------


def test_an_act_without_a_gate_allow_sends_nothing(token):
    driver, effector = _effector()
    call = ApiCall("post_comment", {"body": "hello"})
    plan = effector.preview(THREAD, call)
    with pytest.raises(RefusedActuation):
        effector.act(plan, allow_receipt=None, call=call)
    assert driver.requests == []
    assert effector.selftest() is True


def test_a_deny_receipt_naming_the_right_plan_is_still_not_an_authorization(token):
    """The receipt matches this exact call, and the gate said no. Matching is not
    permission, so the decision is read as well as the target."""
    driver, effector = _effector()
    call = ApiCall("post_comment", {"body": "hello"})
    plan = effector.preview(THREAD, call)
    denied = AccountableSurface().propose(action_kind=plan.action_kind, target=plan.target,
                                          authorization=_grant(["fs.write"]),
                                          observation=effector.perceive(THREAD))
    assert denied.decision != "allow"
    assert denied.request["planned_action"]["target"] == plan.target
    with pytest.raises(RefusedActuation) as exc:
        effector.act(plan, denied, call)
    assert "no gate allow" in str(exc.value)
    assert "POST" not in [r["method"] for r in driver.requests]


def test_an_allow_for_a_different_target_does_not_authorize_this_call(token):
    """A receipt is bound to the plan it was issued for. Carrying one over from
    another thread would let a single approval post anywhere the grant reaches."""
    other = "/repos/octo/demo/issues/99/comments"
    driver = FakeApiDriver({THREAD: [], other: []})
    effector = ApiEffector(driver, GITHUB_ISSUE_COMMENTS)
    call = ApiCall("post_comment", {"body": "hello"})
    elsewhere = effector.preview(other, call)
    allowed = AccountableSurface().propose(action_kind=elsewhere.action_kind, target=elsewhere.target,
                                           authorization=_grant(["api.post"]),
                                           observation=effector.perceive(other))
    assert allowed.decision == "allow"
    with pytest.raises(RefusedActuation) as exc:
        effector.act(effector.preview(THREAD, call), allowed, call)
    assert "does not match the plan" in str(exc.value)
    assert "POST" not in [r["method"] for r in driver.requests]


def test_a_body_that_differs_from_the_previewed_plan_is_refused(token):
    """The gate authorized one body. Swapping it afterwards is not that authorization."""
    driver, effector = _effector()
    authorized = ApiCall("post_comment", {"body": "hello"})
    plan = effector.preview(THREAD, authorized)
    surface = AccountableSurface()
    outcome = surface.propose(action_kind=plan.action_kind, target=plan.target,
                              authorization=_grant(["api.post"]), observation=effector.perceive(THREAD))
    assert outcome.decision == "allow"
    with pytest.raises(RefusedActuation) as exc:
        effector.act(plan, outcome, ApiCall("post_comment", {"body": "something else entirely"}))
    assert "does not match the previewed" in str(exc.value)
    assert [r["method"] for r in driver.requests] == ["GET"]


# --- the credential ----------------------------------------------------------


def test_a_missing_credential_names_the_variable_and_no_value(monkeypatch):
    monkeypatch.delenv(GITHUB_ISSUE_COMMENTS.auth_env, raising=False)
    driver, effector = _effector()
    with pytest.raises(MissingCredential) as exc:
        effector.perceive(THREAD)
    assert GITHUB_ISSUE_COMMENTS.auth_env in str(exc.value)
    assert driver.requests == []


def test_a_credential_carrying_a_newline_is_refused(monkeypatch):
    """A header split is a request-smuggling primitive, so the door rejects it."""
    monkeypatch.setenv(GITHUB_ISSUE_COMMENTS.auth_env, "good\r\nX-Injected: yes")
    _, effector = _effector()
    with pytest.raises(MissingCredential) as exc:
        effector.perceive(THREAD)
    assert "newline" in str(exc.value)


def test_has_secret_reports_presence_without_the_value(monkeypatch):
    monkeypatch.setenv("AS_PROBE_SECRET", "s3cret")
    assert has_secret("AS_PROBE_SECRET") is True
    assert require_secret("AS_PROBE_SECRET") == "s3cret"
    monkeypatch.delenv("AS_PROBE_SECRET")
    assert has_secret("AS_PROBE_SECRET") is False


def test_the_credential_travels_in_a_header_and_never_in_the_url(token):
    driver, effector = _effector()
    effector.perceive(THREAD)
    sent = driver.requests[-1]
    assert sent["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in sent["url"]


def test_a_target_that_smuggles_the_token_into_the_url_is_refused(token):
    """Putting a secret in a query string publishes it: the URL is what gets witnessed
    into the journal, and a proxy log would hold it too."""
    driver, effector = _effector()
    with pytest.raises(RefusedActuation) as exc:
        effector.perceive(f"{THREAD}?access_token={TOKEN}")
    assert "must not appear in the URL" in str(exc.value)
    assert driver.requests == []


def test_the_credential_reaches_no_plan_observation_or_journal_entry(token):
    """The URL is witnessed into the journal, so a secret in one would be published
    into the receipt. Nothing the surface records may carry it."""
    driver, effector = _effector()
    call = ApiCall("post_comment", {"body": "hello"})
    surface = AccountableSurface()
    outcome = surface.actuate(effector, target=THREAD, content=call, authorization=_grant(["api.post"]))
    assert outcome.verified is True
    plan_and_journal = json.dumps([e.to_dict() for e in surface.journal]) + json.dumps(outcome.certificate)
    assert TOKEN not in plan_and_journal
    assert TOKEN not in json.dumps(effector.perceive(THREAD).data)


# --- the whole loop ----------------------------------------------------------


def test_a_granted_comment_is_posted_and_verified_against_the_resource(token):
    driver, effector = _effector()
    surface = AccountableSurface()
    outcome = surface.actuate(effector, target=THREAD, content=ApiCall("post_comment", {"body": "hello"}),
                              authorization=_grant(["api.post"]))
    assert outcome.decision == "allow"
    assert outcome.acted is True
    assert outcome.verified is True
    assert [m["body"] for m in driver._collections[THREAD]] == ["hello"]
    assert [r["method"] for r in driver.requests] == ["GET", "POST", "GET", "GET"]


def test_an_ungranted_action_kind_posts_nothing(token):
    driver, effector = _effector()
    outcome = AccountableSurface().actuate(effector, target=THREAD,
                                           content=ApiCall("post_comment", {"body": "hello"}),
                                           authorization=_grant(["fs.write"]))
    assert outcome.acted is False
    assert driver._collections[THREAD] == []
    assert "POST" not in [r["method"] for r in driver.requests]


def test_rollback_calls_the_services_own_undo(token):
    driver, effector = _effector()
    call = ApiCall("post_comment", {"body": "hello"})
    surface = AccountableSurface()
    surface.actuate(effector, target=THREAD, content=call, authorization=_grant(["api.post"]))
    plan = effector.preview(THREAD, call)
    effector.rollback(plan)
    assert driver._collections[THREAD] == []
    assert driver.requests[-2]["method"] == "DELETE"
    assert driver.requests[-2]["url"].endswith("/repos/octo/demo/issues/comments/1")


# --- irreversibility and grant bounds ---------------------------------------


NO_UNDO = ApiService(
    name="oneway", host="api.github.com", auth_env=GITHUB_ISSUE_COMMENTS.auth_env,
    operations=(ApiOperation(intent="send_message", action_kind="api.post", method="POST",
                             path_shape=r"/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/dispatches"),),
)


def test_a_call_with_no_undo_escalates_to_needs_human(token):
    """Same rule as os.run: no undo means a bare grant is not enough."""
    driver = FakeApiDriver({"/repos/octo/demo/dispatches": []})
    effector = ApiEffector(driver, NO_UNDO)
    outcome = AccountableSurface().actuate(effector, target="/repos/octo/demo/dispatches",
                                           content=ApiCall("send_message", {"body": "go"}),
                                           authorization=_grant(["api.post"]))
    assert outcome.decision == "needs-human"
    assert outcome.acted is False
    assert "POST" not in [r["method"] for r in driver.requests]


def test_an_irreversible_call_the_operator_pre_authorized_cannot_be_rolled_back(token):
    driver = FakeApiDriver({"/repos/octo/demo/dispatches": []})
    effector = ApiEffector(driver, NO_UNDO)
    call = ApiCall("send_message", {"body": "go"})
    outcome = AccountableSurface().actuate(effector, target="/repos/octo/demo/dispatches", content=call,
                                           authorization=_grant(["api.post"]), allow_irreversible=True)
    assert outcome.acted is True and outcome.verified is True
    with pytest.raises(RefusedActuation) as exc:
        effector.rollback(effector.preview("/repos/octo/demo/dispatches", call))
    assert "irreversible" in str(exc.value)


def test_a_grant_bounded_to_one_intent_refuses_an_effector_that_offers_two(token):
    """The grant bounds the effector's reach, not only the action kind: an effector
    built with a wider intent set is not the one the operator granted."""
    wide = ApiService(
        name="github", host="api.github.com", auth_env=GITHUB_ISSUE_COMMENTS.auth_env,
        operations=GITHUB_ISSUE_COMMENTS.operations + (
            ApiOperation(intent="close_issue", action_kind="api.post", method="POST",
                         path_shape=r"/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)"),),
    )
    grant = _grant(["api.post"], bounds=[{"kind": "api", "origins": ["https://api.github.com"],
                                          "intents": ["post_comment"]}])
    driver, narrow = _effector()
    surface = AccountableSurface()
    assert surface.actuate(narrow, target=THREAD, content=ApiCall("post_comment", {"body": "ok"}),
                           authorization=grant).verified is True

    wide_driver = FakeApiDriver({THREAD: []})
    outcome = surface.actuate(ApiEffector(wide_driver, wide), target=THREAD,
                              content=ApiCall("post_comment", {"body": "ok"}), authorization=grant)
    assert outcome.decision == "deny"
    assert outcome.verdict == "bound-not-granted"
    # Honest null: the surface perceives before it refuses, so the ungranted effector
    # still issued its read. The bound refusal governs actuation. Nothing was written.
    assert [r["method"] for r in wide_driver.requests] == ["GET"]
    assert wide_driver._collections[THREAD] == []
