"""Can-it-FAIL negative + redteam tests for the browser effector.

Each test fails the WHOLE suite if the corresponding safety invariant is broken:
a gate-denied action must not execute, re-perception must catch a faulty actor,
a cross-origin bound must hold even under a permissive grant, and an irreversible
script must escalate. These are the falsifiable proofs -- they can go red.
"""

from __future__ import annotations

from accountable_surface.browser_effector import (
    BrowserAction,
    BrowserEffector,
    FakeBrowserDriver,
)
from accountable_surface.surface import AccountableSurface


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-browser-rt",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "browser-agent"},
        "intent": "browser redteam test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _pages():
    return {
        "https://app.test/": {"title": "Home", "fields": {}},
        "https://app.test/expected": {"title": "Expected", "fields": {}},
        "https://app.test/decoy": {"title": "Decoy", "fields": {}},
    }


# --- Test A: gate-denied action must NOT execute -----------------------------

def test_gate_denied_action_refuses_to_navigate():
    """MUST FAIL if an action executes without a gate allow.
    MUST PASS if the surface denies and the browser stays put."""
    drv = FakeBrowserDriver(pages=_pages(), start="https://app.test/")
    eff = BrowserEffector(drv, ["https://app.test"])
    out = AccountableSurface().actuate(
        eff,
        target="https://app.test/",
        content=BrowserAction("navigate", url="https://app.test/expected"),
        authorization={},  # default-deny
    )
    assert out.acted is False, "gate deny must not act"
    assert out.decision == "deny", "decision must be deny"
    assert out.verdict == "not-acted"
    assert drv.current_url() == "https://app.test/", "browser must not navigate"


# --- Test B: re-perception must catch a faulty actor -------------------------

def test_re_perception_catches_wrong_navigation():
    """MUST FAIL if verify() trusts the action's promised post-condition.
    MUST PASS if verify() re-perceives, detects the mismatch, and rolls back."""

    class FaultyDriver(FakeBrowserDriver):
        def navigate(self, url):
            # Bug / hostile: navigate to the WRONG page regardless of intent.
            super().navigate("https://app.test/decoy")

    drv = FaultyDriver(pages=_pages(), start="https://app.test/")
    eff = BrowserEffector(drv, ["https://app.test"])
    out = AccountableSurface().actuate(
        eff,
        target="https://app.test/",
        content=BrowserAction("navigate", url="https://app.test/expected"),
        authorization=_grant(["browser.navigate"]),
    )
    assert out.acted is True, "the (faulty) action executed"
    assert out.verified is False, "verify() MUST detect the mismatch by re-perceiving"
    assert out.rolled_back is True, "a failed reversible act must roll back"
    assert drv.current_url() == "https://app.test/", "rollback restored the before-state"


# --- Test C: cross-origin bound holds even with a permissive grant -----------

def test_cross_origin_refused_by_effector_bound():
    """MUST FAIL if an origin-bounded effector navigates off the allowlist.
    MUST PASS if the effector's origin bound refuses even under a grant."""
    drv = FakeBrowserDriver(pages={"https://ok.test/": {"title": "OK", "fields": {}}}, start="https://ok.test/")
    eff = BrowserEffector(drv, allowed_origins=["https://ok.test"])
    out = AccountableSurface().actuate(
        eff,
        target="https://ok.test/",
        content=BrowserAction("navigate", url="https://evil.test/"),
        authorization=_grant(["browser.navigate"]),  # gate is permissive
    )
    assert out.acted is False, "must not act off-origin"
    assert out.verdict == "refused-by-effector", "refused by the effector bound, not the gate"
    assert drv.current_url() == "https://ok.test/", "browser stayed put"


# --- Test C2: a CLICK that client-side-navigates off-origin is refused --------

def test_click_cross_origin_navigation_refused_by_effector_bound():
    """MUST FAIL if a click's client-side navigation escapes the allowlist and is
    reported as a verified action. MUST PASS if the effector detects the off-origin
    landing, rolls the page back, and refuses -- the origin bound must hold for the
    click's DESTINATION, not just the page the click is dispatched from.

    This is the SPA-specific gap: `navigate` targets are pre-checked, but a click
    fires a client-side handler that can route anywhere the page declares."""
    pages = {
        "https://app.test/": {
            "title": "Home",
            "fields": {},
            # the click handler routes to an OFF-ALLOWLIST origin (an open-redirect
            # / hijacked SPA link -- exactly what the origin bound must contain).
            "clicks": {"Leave": "https://evil.test/landing"},
        },
        "https://app.test/expected": {"title": "Expected", "fields": {}},
    }
    drv = FakeBrowserDriver(pages=pages, start="https://app.test/")
    eff = BrowserEffector(drv, allowed_origins=["https://app.test"])
    out = AccountableSurface().actuate(
        eff,
        target="https://app.test/",
        content=BrowserAction("click", url="https://app.test/", selector="Leave"),
        authorization=_grant(["browser.click"]),  # gate is permissive
    )
    assert out.acted is False, "a click that lands off-origin must NOT count as acting"
    assert out.verdict == "refused-by-effector", "refused by the effector's origin bound"
    assert drv.current_url() == "https://app.test/", "the off-origin navigation was rolled back"


# --- Test D: irreversible script escalates without permission ----------------

def test_irreversible_script_escalates():
    """MUST FAIL if a script side-effect executes without explicit permission.
    MUST PASS if the surface escalates to needs-human."""
    drv = FakeBrowserDriver(pages={"https://app.test/": {"title": "Home", "fields": {}}}, start="https://app.test/")
    eff = BrowserEffector(drv, ["https://app.test"])
    out = AccountableSurface().actuate(
        eff,
        target="https://app.test/",
        content=BrowserAction("evaluate", url="https://app.test/", value="localStorage.clear()"),
        authorization=_grant(["browser.evaluate"]),
        allow_irreversible=False,  # default: escalate irreversible
    )
    assert out.acted is False, "must not execute the script"
    assert out.decision == "needs-human", "must escalate an irreversible action"


def test_irreversible_script_with_permission_runs():
    """The mirror of Test D: with explicit allow_irreversible the script runs."""
    drv = FakeBrowserDriver(pages={"https://app.test/": {"title": "Home", "fields": {}}}, start="https://app.test/")
    eff = BrowserEffector(drv, ["https://app.test"])
    out = AccountableSurface().actuate(
        eff,
        target="https://app.test/",
        content=BrowserAction("evaluate", url="https://app.test/", value="document.title"),
        authorization=_grant(["browser.evaluate"]),
        allow_irreversible=True,
    )
    assert out.acted is True
