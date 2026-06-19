"""Tests for native web actuation — WebEffector (Phase 5, second effector).

Offline + deterministic via FakePageDriver (no browser, no external deps). Proves
the same accountability invariants as FilesystemEffector — inert until authorized,
origin-bounded, verified by re-perceiving — now on the page's structure (navigate,
fill by accessible label).
"""

from __future__ import annotations

import pytest

from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import FakePageDriver, WebAction, WebEffector


class _Allow:
    decision = "allow"

    def __init__(self, action_kind, target):
        self.request = {"planned_action": {"action_kind": action_kind, "target": target}}


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-web-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "web-agent"},
        "intent": "web actuation test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _driver():
    return FakePageDriver(
        pages={
            "https://ok.test/": {"title": "home", "fields": {}},
            "https://ok.test/form": {"title": "form", "fields": {"Email": ""}},
        },
        start="https://ok.test/",
    )


def test_perceive_snapshots_structure():
    eff = WebEffector(_driver(), allowed_origins=["https://ok.test"])
    obs = eff.perceive()
    assert obs.organ == "web-effector"
    assert obs.data["url"] == "https://ok.test/"
    assert obs.provenance.digest.startswith("sha256:")


def test_navigate_without_allow_refuses():
    drv = _driver()
    eff = WebEffector(drv, allowed_origins=["https://ok.test"])
    action = WebAction("navigate", url="https://ok.test/form")
    plan = eff.preview("https://ok.test/", action)
    with pytest.raises(Exception):
        eff.act(plan, allow_receipt=None, action=action)
    assert drv.current_url() == "https://ok.test/"  # did not navigate


def test_navigate_outside_origin_refuses_even_with_allow():
    drv = _driver()
    eff = WebEffector(drv, allowed_origins=["https://ok.test"])
    action = WebAction("navigate", url="https://evil.test/")
    plan = eff.preview("https://ok.test/", action)
    with pytest.raises(Exception):
        eff.act(plan, _Allow("web.navigate", "https://evil.test/"), action=action)
    assert drv.current_url() == "https://ok.test/"  # bounded by construction


def test_navigate_with_allow_acts_and_verifies():
    drv = _driver()
    eff = WebEffector(drv, allowed_origins=["https://ok.test"])
    action = WebAction("navigate", url="https://ok.test/form")
    plan = eff.preview("https://ok.test/", action)
    after = eff.act(plan, _Allow("web.navigate", "https://ok.test/form"), action=action)
    assert drv.current_url() == "https://ok.test/form"
    assert eff.verify(plan, after).status == "pass"


def test_fill_by_label_acts_and_verifies():
    drv = _driver()
    drv.navigate("https://ok.test/form")
    eff = WebEffector(drv, allowed_origins=["https://ok.test"])
    action = WebAction("fill", url="https://ok.test/form", selector="Email", value="a@b.c")
    plan = eff.preview("https://ok.test/form", action, eff.perceive())
    after = eff.act(plan, _Allow("web.fill", "https://ok.test/form#Email"), action=action)
    assert drv.field_value("Email") == "a@b.c"
    assert eff.verify(plan, after).status == "pass"


def test_fill_rollback_restores_prior_value():
    drv = _driver()
    drv.navigate("https://ok.test/form")
    drv.fill("Email", "old@x.y")
    eff = WebEffector(drv, allowed_origins=["https://ok.test"])
    action = WebAction("fill", url="https://ok.test/form", selector="Email", value="new@x.y")
    plan = eff.preview("https://ok.test/form", action, eff.perceive())
    eff.act(plan, _Allow("web.fill", "https://ok.test/form#Email"), action=action)
    assert drv.field_value("Email") == "new@x.y"
    eff.rollback(plan)
    assert drv.field_value("Email") == "old@x.y"


def test_selftest_holds():
    assert WebEffector(_driver(), allowed_origins=["https://ok.test"]).selftest() is True


# --- the actuate loop with the web effector ------------------------------

def test_actuate_no_grant_does_not_navigate():
    drv = _driver()
    s = AccountableSurface()
    out = s.actuate(
        WebEffector(drv, allowed_origins=["https://ok.test"]),
        target="https://ok.test/",
        content=WebAction("navigate", url="https://ok.test/form"),
        authorization={},
    )
    assert out.acted is False
    assert out.decision == "deny"
    assert drv.current_url() == "https://ok.test/"  # no effect


def test_actuate_authorized_navigation_verifies_and_journals():
    drv = _driver()
    s = AccountableSurface()
    out = s.actuate(
        WebEffector(drv, allowed_origins=["https://ok.test"]),
        target="https://ok.test/",
        content=WebAction("navigate", url="https://ok.test/form"),
        authorization=_grant(["web.navigate"]),
    )
    assert out.acted is True
    assert out.verified is True
    assert drv.current_url() == "https://ok.test/form"
    assert any(e.kind == "actuation" for e in s.journal)


def test_actuate_permissive_grant_still_bounded_by_effector():
    # The gate would allow it (empty allowed_targets), but the effector's origin
    # bound is a stricter second gate: the surface reports refused-by-effector,
    # never crashes, and nothing navigates off-origin.
    drv = _driver()
    s = AccountableSurface()
    out = s.actuate(
        WebEffector(drv, allowed_origins=["https://ok.test"]),
        target="https://ok.test/",
        content=WebAction("navigate", url="https://evil.test/"),
        authorization=_grant(["web.navigate"]),
    )
    assert out.acted is False
    assert out.verdict == "refused-by-effector"
    assert drv.current_url() == "https://ok.test/"


# --- form submit (POST) — an irreversible action ----------------------------

def _site_with_thanks():
    drv = FakePageDriver(
        pages={
            "https://ok.test/form": {"title": "form", "fields": {"Email": ""}},
            "https://ok.test/thanks": {"title": "Thanks", "fields": {}},
        },
        start="https://ok.test/form",
    )
    return WebEffector(drv, allowed_origins=["https://ok.test"]), drv


def test_submit_is_irreversible_in_the_plan():
    eff, _ = _site_with_thanks()
    plan = eff.preview("https://ok.test/form", WebAction("submit", url="https://ok.test/thanks", value="Thanks"))
    assert plan.action_kind == "web.submit"
    assert plan.reversible is False


def test_submit_acts_and_verifies_by_response():
    eff, drv = _site_with_thanks()
    drv.fill("Email", "neo@x.io")
    action = WebAction("submit", url="https://ok.test/thanks", value="Thanks")
    plan = eff.preview("https://ok.test/form", action, eff.perceive())
    after = eff.act(plan, _Allow("web.submit", "https://ok.test/thanks"), action=action)
    assert drv.current_url() == "https://ok.test/thanks"
    assert eff.verify(plan, after).status == "pass"  # the response title confirms


def test_actuate_submit_escalates_without_irreversible_permission():
    eff, drv = _site_with_thanks()
    out = AccountableSurface().actuate(
        eff, target="https://ok.test/form",
        content=WebAction("submit", url="https://ok.test/thanks", value="Thanks"),
        authorization=_grant(["web.submit"]),
    )
    assert out.acted is False
    assert out.decision == "needs-human"  # a POST is irreversible
    assert drv.current_url() == "https://ok.test/form"  # did NOT submit


def test_actuate_submit_with_irreversible_permission_acts():
    eff, drv = _site_with_thanks()
    out = AccountableSurface().actuate(
        eff, target="https://ok.test/form",
        content=WebAction("submit", url="https://ok.test/thanks", value="Thanks"),
        authorization=_grant(["web.submit"]), allow_irreversible=True,
    )
    assert out.acted is True
    assert out.verified is True
    assert drv.current_url() == "https://ok.test/thanks"
