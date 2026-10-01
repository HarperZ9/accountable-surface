"""Irreversible actuation needs the operator's grant, not only a caller argument.

`allow_irreversible=True` used to be enough on its own: any code holding a valid
grant for `web.submit` could pass the flag and submit. The authority now lives in the
grant (`scope.allowed_irreversible_actions`, a list of exact action kinds). The caller
flag stays as a second, narrowing opt-in: both must hold.
"""
from __future__ import annotations

import pytest

from accountable_surface.surface import AccountableSurface, Step
from accountable_surface.web_effector import FakePageDriver, WebAction, WebEffector


def _grant(actions, irreversible=None):
    scope = {"allowed_actions": list(actions), "allowed_targets": []}
    if irreversible is not None:
        scope["allowed_irreversible_actions"] = irreversible
    return {
        "authorization_version": "0.1", "receipt_id": "rcpt-irrev-1",
        "kind": "authorization-grant", "principal": {"id": "operator", "role": "operator"},
        "agent": {"id": "agent"}, "intent": "irreversibility tests", "scope": scope,
        "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _submit(grant, allow_irreversible):
    pages = {"https://app.test/form": {"title": "Form", "fields": {"q": "data"}},
             "https://app.test/result": {"title": "ok", "fields": {}}}
    driver = FakePageDriver(pages, start="https://app.test/form")
    eff = WebEffector(driver, allowed_origins=["https://app.test"])
    out = AccountableSurface().actuate(
        eff, target="https://app.test/result",
        content=WebAction("submit", url="https://app.test/result", value="ok"),
        authorization=grant, allow_irreversible=allow_irreversible)
    return out, driver


def test_caller_flag_alone_no_longer_authorizes_an_irreversible_act():
    out, driver = _submit(_grant(["web.submit"]), allow_irreversible=True)
    assert out.acted is False
    assert out.decision == "needs-human"
    assert out.verdict == "irreversible-needs-human"
    assert any("allowed_irreversible_actions" in r for r in out.reasons)
    assert driver.current_url() == "https://app.test/form"


def test_grant_plus_caller_flag_acts():
    out, driver = _submit(_grant(["web.submit"], irreversible=["web.submit"]), allow_irreversible=True)
    assert out.acted is True and out.decision == "allow"
    assert driver.current_url() == "https://app.test/result"


def test_grant_alone_without_caller_flag_still_escalates():
    """The caller can narrow: a grant permits, it does not force."""
    out, _ = _submit(_grant(["web.submit"], irreversible=["web.submit"]), allow_irreversible=False)
    assert out.acted is False and out.verdict == "irreversible-needs-human"


def test_grant_for_a_different_kind_does_not_cover_this_one():
    out, _ = _submit(_grant(["web.submit"], irreversible=["os.run"]), allow_irreversible=True)
    assert out.acted is False and out.verdict == "irreversible-needs-human"


@pytest.mark.parametrize("value", ["*", ["*"], True, "web.submit", "web.submit,os.run", {"web.submit": 1}])
def test_only_an_explicit_list_of_kinds_counts(value):
    """No wildcard, no boolean, and no string (a substring test would match `web.submit`)."""
    out, _ = _submit(_grant(["web.submit"], irreversible=value), allow_irreversible=True)
    assert out.acted is False and out.decision == "needs-human"


def test_pursue_with_flag_but_no_grant_halts_before_acting():
    pages = {"https://app.test/form": {"title": "Form", "fields": {}},
             "https://app.test/result": {"title": "ok", "fields": {}}}
    driver = FakePageDriver(pages, start="https://app.test/form")
    eff = WebEffector(driver, allowed_origins=["https://app.test"])
    steps = [Step(eff, "https://app.test/result", WebAction("submit", url="https://app.test/result"))]
    out = AccountableSurface().pursue("submit", steps, authorization=_grant(["web.submit"]),
                                      allow_irreversible=True)
    assert out.achieved is False
    assert driver.current_url() == "https://app.test/form"


def test_the_new_scope_field_is_stripped_before_the_closed_gate_schema():
    from accountable_surface.grant import LOCAL_SCOPE_FIELDS, action_authorization
    assert "allowed_irreversible_actions" in LOCAL_SCOPE_FIELDS
    stripped = action_authorization(_grant(["web.submit"], irreversible=["web.submit"]))
    assert "allowed_irreversible_actions" not in stripped["scope"]
