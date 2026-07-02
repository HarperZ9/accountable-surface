"""Tests for the JavaScript-capable browser effector -- BrowserEffector.

Offline + deterministic via FakeBrowserDriver (no browser binary, no external
deps). Proves the SAME accountability invariants as FilesystemEffector and
WebEffector -- inert until authorized, origin-bounded, verified by re-perceiving,
reversible-or-escalate -- now over a live JS-capable page (execute JS, click by
accessible label, follow cross-origin navigation) so the loop drives SPAs.

The real headless-browser backend (PlaywrightDriver) is optional and NOT
exercised here: every test injects the deterministic stub.
"""

from __future__ import annotations

import pytest

from accountable_surface.browser_effector import (
    BrowserAction,
    BrowserEffector,
    FakeBrowserDriver,
)
from accountable_surface.surface import AccountableSurface


class _Allow:
    decision = "allow"

    def __init__(self, action_kind, target):
        self.request = {"planned_action": {"action_kind": action_kind, "target": target}}


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-browser-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "browser-agent"},
        "intent": "browser actuation test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _spa():
    """A tiny SPA model: home + an app page reached by a client-side click, plus a
    cross-origin auth page on a second allowed origin."""
    return FakeBrowserDriver(
        pages={
            "https://spa.test/": {
                "title": "Home",
                "fields": {"Search": ""},
                "clicks": {"Open app": "https://spa.test/app"},
            },
            "https://spa.test/app": {
                "title": "App",
                "fields": {"Email": ""},
            },
            "https://auth.test/login": {
                "title": "Login",
                "fields": {"Password": ""},
            },
        },
        start="https://spa.test/",
    )


def _eff(driver=None, origins=("https://spa.test", "https://auth.test")):
    return BrowserEffector(driver or _spa(), allowed_origins=list(origins))


# --- perception --------------------------------------------------------------

def test_perceive_snapshots_accessibility_tree():
    obs = _eff().perceive()
    assert obs.organ == "browser-effector"
    assert obs.data["url"] == "https://spa.test/"
    assert obs.data["title"] == "Home"
    assert obs.provenance.digest.startswith("sha256:")


# --- inert until authorized --------------------------------------------------

def test_navigate_without_allow_refuses():
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("navigate", url="https://spa.test/app")
    plan = eff.preview("https://spa.test/", action)
    with pytest.raises(Exception):
        eff.act(plan, allow_receipt=None, action=action)
    assert drv.current_url() == "https://spa.test/"


def test_click_without_allow_refuses():
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("click", url="https://spa.test/", selector="Open app")
    plan = eff.preview("https://spa.test/", action)
    with pytest.raises(Exception):
        eff.act(plan, allow_receipt=None, action=action)
    assert drv.current_url() == "https://spa.test/"  # click did not fire


# --- click by label triggers client-side navigation (JS-capable) -------------

def test_click_by_label_navigates_and_verifies():
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("click", url="https://spa.test/", selector="Open app")
    plan = eff.preview("https://spa.test/", action, eff.perceive())
    after = eff.act(plan, _Allow("browser.click", plan.target), action=action)
    assert drv.current_url() == "https://spa.test/app"
    assert eff.verify(plan, after).status == "pass"  # page changed -> click took effect


def test_click_that_has_no_effect_fails_verify():
    # A label that does not exist -> the page does not change -> verify FAILS.
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("click", url="https://spa.test/", selector="Nonexistent")
    plan = eff.preview("https://spa.test/", action, eff.perceive())
    after = eff.act(plan, _Allow("browser.click", plan.target), action=action)
    assert drv.current_url() == "https://spa.test/"
    assert eff.verify(plan, after).status == "failed"


# --- fill by label -----------------------------------------------------------

def test_fill_by_label_acts_and_verifies():
    drv = _spa()
    drv.navigate("https://spa.test/app")
    eff = _eff(drv)
    action = BrowserAction("fill", url="https://spa.test/app", selector="Email", value="a@b.c")
    plan = eff.preview("https://spa.test/app", action, eff.perceive())
    after = eff.act(plan, _Allow("browser.fill", plan.target), action=action)
    assert drv.field_value("Email") == "a@b.c"
    assert eff.verify(plan, after).status == "pass"


def test_fill_rollback_restores_prior_value():
    drv = _spa()
    drv.navigate("https://spa.test/app")
    drv.fill("Email", "old@x.y")
    eff = _eff(drv)
    action = BrowserAction("fill", url="https://spa.test/app", selector="Email", value="new@x.y")
    plan = eff.preview("https://spa.test/app", action, eff.perceive())
    eff.act(plan, _Allow("browser.fill", plan.target), action=action)
    assert drv.field_value("Email") == "new@x.y"
    eff.rollback(plan)
    assert drv.field_value("Email") == "old@x.y"


# --- cross-origin navigation (the SPA differentiator) ------------------------

def test_cross_origin_navigation_within_allowlist_verifies():
    # BrowserEffector may follow navigation across MULTIPLE allowed origins.
    drv = _spa()
    eff = _eff(drv)  # allows both spa.test and auth.test
    action = BrowserAction("navigate", url="https://auth.test/login")
    plan = eff.preview("https://spa.test/", action, eff.perceive())
    after = eff.act(plan, _Allow("browser.navigate", plan.target), action=action)
    assert drv.current_url() == "https://auth.test/login"
    assert eff.verify(plan, after).status == "pass"


def test_navigate_rollback_goes_back():
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("navigate", url="https://auth.test/login")
    plan = eff.preview("https://spa.test/", action, eff.perceive())
    eff.act(plan, _Allow("browser.navigate", plan.target), action=action)
    assert drv.current_url() == "https://auth.test/login"
    eff.rollback(plan)
    assert drv.current_url() == "https://spa.test/"


# --- JavaScript evaluation (irreversible) ------------------------------------

def test_evaluate_is_irreversible_in_the_plan():
    eff = _eff()
    plan = eff.preview("https://spa.test/", BrowserAction("evaluate", url="https://spa.test/", value="document.title"))
    assert plan.action_kind == "browser.evaluate"
    assert plan.reversible is False


def test_evaluate_runs_js_and_records_result():
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("evaluate", url="https://spa.test/", value="document.title")
    plan = eff.preview("https://spa.test/", action, eff.perceive())
    after = eff.act(plan, _Allow("browser.evaluate", plan.target), action=action)
    # The deterministic stub returns the page title for `document.title`.
    assert after.data.get("last_eval") == "Home"


def test_evaluate_rollback_refuses():
    drv = _spa()
    eff = _eff(drv)
    action = BrowserAction("evaluate", url="https://spa.test/", value="localStorage.clear()")
    plan = eff.preview("https://spa.test/", action, eff.perceive())
    eff.act(plan, _Allow("browser.evaluate", plan.target), action=action)
    with pytest.raises(Exception):
        eff.rollback(plan)


# --- selftest ----------------------------------------------------------------

def test_selftest_holds():
    assert _eff().selftest() is True


# --- the actuate loop with the browser effector ------------------------------

def test_actuate_no_grant_does_not_navigate():
    drv = _spa()
    out = AccountableSurface().actuate(
        _eff(drv),
        target="https://spa.test/",
        content=BrowserAction("navigate", url="https://spa.test/app"),
        authorization={},
    )
    assert out.acted is False
    assert out.decision == "deny"
    assert drv.current_url() == "https://spa.test/"


def test_actuate_authorized_click_verifies_and_journals():
    drv = _spa()
    s = AccountableSurface()
    out = s.actuate(
        _eff(drv),
        target="https://spa.test/",
        content=BrowserAction("click", url="https://spa.test/", selector="Open app"),
        authorization=_grant(["browser.click"]),
    )
    assert out.acted is True
    assert out.verified is True
    assert drv.current_url() == "https://spa.test/app"
    assert any(e.kind == "actuation" for e in s.journal)


def test_actuate_multistep_spa_journey():
    # perceive home -> click into the app -> fill an email, all under one grant.
    drv = _spa()
    s = AccountableSurface()
    from accountable_surface.surface import Step

    eff = _eff(drv)
    steps = [
        Step(eff, "https://spa.test/", BrowserAction("click", url="https://spa.test/", selector="Open app")),
        Step(eff, "https://spa.test/app", BrowserAction("fill", url="https://spa.test/app", selector="Email", value="user@x.io")),
    ]
    result = s.pursue(
        "Open the app and fill the email",
        steps,
        authorization=_grant(["browser.click", "browser.fill"]),
    )
    assert result.achieved is True
    assert result.steps_acted == 2
    assert drv.field_value("Email") == "user@x.io"
