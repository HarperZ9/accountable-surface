"""JS-capable browser actuation over an SPA -- runnable transcript, fully offline.

Drives a single-page-app journey (click into the app by accessible label, fill a
field, cross-origin navigate to an auth page, run JS) through the SAME accountable
loop as every other effector: perceive -> plan -> gate -> act -> re-perceive ->
verify -> journal. Nothing acts without an operator grant; an irreversible script
escalates to needs-human.

This demo injects the deterministic `FakeBrowserDriver`, so it needs NO browser and
NO external dependency. To drive a real live SPA instead, install the optional
backend and swap ONE line:

    pip install "accountable-surface[browser]"
    python -m playwright install chromium

    from accountable_surface.playwright_driver import PlaywrightDriver
    driver = PlaywrightDriver(headless=True, start="https://spa.example.com/")

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/spa_actuate_demo.py
"""

from __future__ import annotations

from accountable_surface.browser_effector import (
    BrowserAction,
    BrowserEffector,
    FakeBrowserDriver,
)
from accountable_surface.surface import AccountableSurface, Step


def _grant(actions):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-spademo",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "spademo"},
        "intent": "open the app, fill a field, cross-origin navigate",
        "scope": {"allowed_actions": list(actions), "allowed_targets": []},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _spa_driver():
    return FakeBrowserDriver(
        pages={
            "https://spa.test/": {
                "title": "Home",
                "fields": {"Search": ""},
                "clicks": {"Open app": "https://spa.test/app"},
            },
            "https://spa.test/app": {"title": "App", "fields": {"Email": ""}},
            "https://auth.test/login": {"title": "Login", "fields": {"Password": ""}},
        },
        start="https://spa.test/",
    )


def main() -> None:
    drv = _spa_driver()
    eff = BrowserEffector(drv, allowed_origins=["https://spa.test", "https://auth.test"])
    surface = AccountableSurface()

    print("== JS-capable SPA actuation (FakeBrowserDriver, offline, no browser) ==\n")

    home = eff.perceive()
    print("== PERCEIVE home (witnessed a11y tree, not a screenshot) ==")
    print(f"  url: {home.data['url']}   title: {home.data['title']!r}   digest: {home.provenance.digest[:23]}...\n")

    print("== A gated SPA journey: CLICK 'Open app' -> FILL 'Email' (one grant) ==")
    steps = [
        Step(eff, "https://spa.test/", BrowserAction("click", url="https://spa.test/", selector="Open app")),
        Step(eff, "https://spa.test/app", BrowserAction("fill", url="https://spa.test/app", selector="Email", value="neo@frontier.io")),
    ]
    result = surface.pursue("Open the app and fill the email", steps,
                            authorization=_grant(["browser.click", "browser.fill"]))
    print(f"  achieved: {result.achieved}  steps_acted: {result.steps_acted}/{len(steps)}  now at: {drv.current_url()}")
    print(f"  Email now: {drv.field_value('Email')!r}\n")

    print("== CROSS-ORIGIN navigate -> auth.test (on the allowlist) ==")
    out = surface.actuate(eff, target="https://spa.test/app",
                          content=BrowserAction("navigate", url="https://auth.test/login"),
                          authorization=_grant(["browser.navigate"]))
    print(f"  acted: {out.acted}  verified: {out.verified}  now at: {drv.current_url()}\n")

    print("== CROSS-ORIGIN navigate -> evil.test (OFF the allowlist) ==")
    out = surface.actuate(eff, target="https://auth.test/login",
                          content=BrowserAction("navigate", url="https://evil.test/"),
                          authorization=_grant(["browser.navigate"]))
    print(f"  acted: {out.acted}  verdict: {out.verdict}  still at: {drv.current_url()}\n")

    print("== EVALUATE JS (irreversible) without allow_irreversible -> escalates ==")
    out = surface.actuate(eff, target="https://auth.test/login",
                          content=BrowserAction("evaluate", url="https://auth.test/login", value="localStorage.clear()"),
                          authorization=_grant(["browser.evaluate"]))
    print(f"  acted: {out.acted}  decision: {out.decision}\n")

    print("== JOURNAL (every actuation, witnessed) ==")
    for entry in surface.journal:
        if entry.kind in ("actuation", "goal"):
            print(f"  [{entry.kind}] {entry.summary}")


if __name__ == "__main__":
    main()
