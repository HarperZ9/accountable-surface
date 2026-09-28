"""Per-target tiers (R6): read, click, full, with class ceilings in code.

A grant names a tier per target (an origin for the browser and web paths, a
window for the desktop path). A class ceiling in code caps it: a browser window
on the desktop path is `read`, a terminal or IDE is `click`, a credential or
security surface is `read`. A grant can narrow a ceiling and never widen it.
"""

from __future__ import annotations

from accountable_surface import tiers
from accountable_surface.grant import action_authorization

NOTEPAD = {"title": "Untitled - Notepad", "image": "C:/Windows/System32/notepad.exe"}


def _grant(*entries):
    return {"scope": {"allowed_actions": ["browser.fill"], "target_tiers": list(entries)}}


def test_required_tier_by_action():
    assert tiers.required_tier("browser.navigate") == "click"
    assert tiers.required_tier("browser.click") == "click"
    assert tiers.required_tier("web.submit") == "click"
    assert tiers.required_tier("browser.fill") == "full"
    assert tiers.required_tier("uia.set_value") == "full"
    assert tiers.required_tier("api.create_issue") == "full"
    assert tiers.required_tier("perceive") == "read"
    assert tiers.required_tier("something.unknown") == "full"


def test_origin_target_uses_its_granted_tier():
    grant = _grant({"origin": "http://127.0.0.1:8765", "tier": "click"})
    ok = tiers.check("browser.click", {"origin": "http://127.0.0.1:8765"}, grant)
    assert ok.allowed and ok.effective == "click"
    no = tiers.check("browser.fill", {"origin": "http://127.0.0.1:8765"}, grant)
    assert not no.allowed and "needs full" in no.reason


def test_ungranted_target_is_refused():
    grant = _grant({"origin": "http://127.0.0.1:8765", "tier": "full"})
    result = tiers.check("browser.click", {"origin": "http://127.0.0.1:9999"}, grant)
    assert not result.allowed and result.granted is None


def test_grant_cannot_raise_a_class_ceiling():
    chrome = {"title": "Inbox", "image": "C:/Program Files/Google/Chrome/Application/chrome.exe"}
    grant = _grant({"window": chrome, "tier": "full"})
    result = tiers.check("uia.invoke", {"window": chrome}, grant)
    assert (result.granted, result.ceiling, result.effective) == ("full", "read", "read")
    assert not result.allowed
    term = {"title": "PowerShell", "image": "C:/Program Files/PowerShell/7/pwsh.exe"}
    assert tiers.check("uia.set_value", {"window": term}, _grant({"window": term, "tier": "full"})).effective == "click"
    cred = {"title": "Windows Security", "image": "C:/Windows/System32/CredentialUIBroker.exe"}
    assert tiers.check("uia.invoke", {"window": cred}, _grant({"window": cred, "tier": "full"})).effective == "read"


def test_title_match_with_the_wrong_image_is_refused():
    grant = _grant({"window": NOTEPAD, "tier": "full"})
    impostor = {"title": "Untitled - Notepad", "image": "C:/Users/x/Downloads/notepad.exe"}
    result = tiers.check("uia.set_value", {"window": impostor}, grant)
    assert not result.allowed and "image" in result.reason
    assert tiers.check("uia.set_value", {"window": dict(NOTEPAD)}, grant).allowed


def test_click_tier_refuses_set_value():
    grant = _grant({"window": NOTEPAD, "tier": "click"})
    assert tiers.check("uia.invoke", {"window": NOTEPAD}, grant).allowed
    assert not tiers.check("uia.set_value", {"window": NOTEPAD}, grant).allowed


def test_clipboard_needs_its_own_flag():
    grant = _grant({"window": NOTEPAD, "tier": "full"})
    result = tiers.check("clipboard.write", {"window": NOTEPAD}, grant)
    assert not result.allowed and "clipboard_write" in result.reason
    flagged = _grant({"window": NOTEPAD, "tier": "full", "clipboard_write": True})
    assert tiers.check("clipboard.write", {"window": NOTEPAD}, flagged).allowed


def test_a_tier_the_code_does_not_know_is_refused():
    grant = _grant({"origin": "http://127.0.0.1:8765", "tier": "admin"})
    assert not tiers.check("browser.click", {"origin": "http://127.0.0.1:8765"}, grant).allowed


def test_target_tiers_never_reaches_the_closed_gate_schema():
    grant = {"scope": {"allowed_actions": ["x"], "allowed_targets": ["t"], "target_tiers": [{"origin": "o", "tier": "full"}]}}
    assert action_authorization(grant)["scope"] == {"allowed_actions": ["x"], "allowed_targets": ["t"]}
    assert "target_tiers" in grant["scope"]  # the original is not mutated
