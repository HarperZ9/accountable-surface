"""The accountable pipeline driving a real headless Chromium on 127.0.0.1 (E4, A2, C1).

Run with `python -m pytest -m live tests/live`. Each test starts the fixture
site on 127.0.0.1 and a fresh Chromium through PlaywrightDriver; nothing reaches
beyond the machine and no everyday browser profile is touched.

The same negative controls as the stdlib suite, now in a real browser: a
password field, a card number, a CAPTCHA widget and a 403 challenge answer, a
"Submit order" button, and a page whose text tells the agent what to do. Each
is refused, stopped, or held with a receipt that says why, and the DOM shows
nothing was typed or sent. The browser declares itself automated.
"""

from __future__ import annotations

import json

import pytest
from actuation_world import CARD, PASSWORD, Console

from accountable_surface import authority_cli, rederive
from accountable_surface.actuation_receipt import ReceiptLog
from accountable_surface.approvals import ApprovalStore
from accountable_surface.browser_effector import BrowserEffector
from accountable_surface.evidence import EvidenceStore
from accountable_surface.pipeline import ActuationPipeline
from accountable_surface.surface import AccountableSurface

pytestmark = pytest.mark.live
KINDS = ["browser.navigate", "browser.fill", "browser.click", "browser.evaluate"]


def grant(origin):
    return {"authorization_version": "0.1", "receipt_id": "rcpt-live", "kind": "authorization-grant",
            "principal": {"id": "operator-1", "role": "operator"}, "agent": {"id": "live-agent"},
            "intent": "live browser fixture", "scope": {"allowed_actions": KINDS, "allowed_targets": [],
                                                        "target_tiers": [{"origin": origin, "tier": "full"}]},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00",
            "revoked": False}


class LiveWorld:
    def __init__(self, tmp_path, site, driver):
        self.tmp, self.site, self.driver = tmp_path, site, driver
        self.store = ApprovalStore(tmp_path / "authority.db")
        self.receipts = ReceiptLog(tmp_path / "receipts.jsonl")
        self.evidence = EvidenceStore(tmp_path / "evidence")
        self.pipe = ActuationPipeline(AccountableSurface(journal_path=tmp_path / "journal.jsonl"),
                                      BrowserEffector(driver, allowed_origins=[site.origin]),
                                      grant=grant(site.origin), approvals=self.store, receipts=self.receipts,
                                      evidence=self.evidence)

    def step(self, sid, kind, path, control=None, args=None, post=None):
        target = {"origin": self.site.origin, "path": path}
        if control:
            target["control"] = control
        return self.pipe.run_step({"step_id": sid, "action_kind": kind, "target": target, "args": args or {},
                                   "post_condition": post})

    def nav(self, path):
        return self.step(f"nav{path}", "browser.navigate", path, post={"kind": "url_is", "value": self.site.url(path)})

    def fill(self, path, name, value, sid="fill"):
        return self.step(sid, "browser.fill", path, {"name": name}, {"value": value},
                         {"kind": "field_value_is", "control": {"name": name}, "value": value})

    def submit_order(self):
        return self.step("submit", "browser.click", "/order", {"name": "Submit order", "role": "button"},
                         post={"kind": "text_present", "path": "/orders", "value": "Order 1: quantity 1"})

    def dom(self, script):
        return self.driver._run(self.driver._page.evaluate(script))  # a read that leaves no call record

    def all_bytes(self):
        paths = [self.receipts.path, self.store.path, self.tmp / "journal.jsonl"]
        paths += [p for p in self.evidence.root.rglob("*") if p.is_file()] if self.evidence.root.exists() else []
        return b"".join(p.read_bytes() for p in paths if p.exists())


def rules(result):
    return {h["rule"] for h in result.policy["rule_hits"]}


@pytest.fixture
def world(tmp_path, site, chromium):
    return LiveWorld(tmp_path, site, chromium)


def test_navigator_webdriver_is_true(world):
    world.nav("/notes")
    assert world.dom("navigator.webdriver") is True


def test_navigate_and_fill_verify_and_the_session_re_derives(world):
    assert world.nav("/notes").verdict == "verified"
    result = world.fill("/notes", "Title", "weekly notes")
    assert (result.status, result.verdict) == ("acted", "verified")
    assert world.dom("document.getElementById('title').value") == "weekly notes"
    report = rederive.rederive(world.receipts.path, world.evidence.root)
    assert report["verdict"] == "MATCH", json.dumps(report["levels"])


def test_a_password_field_is_refused_and_nothing_is_typed(world):
    world.nav("/login")
    result = world.fill("/login", "Password", PASSWORD)
    assert result.status == "refused" and "R4.secret-field" in rules(result)
    assert world.dom("document.getElementById('password').value") == ""
    assert not any(c.startswith("fill") for c in world.driver.calls)
    assert PASSWORD.encode() not in world.all_bytes()


def test_a_card_number_is_refused_in_the_card_field_and_in_notes(world):
    world.nav("/checkout")
    card = world.fill("/checkout", "Card number", CARD, sid="card")
    notes = world.fill("/checkout", "Notes", CARD, sid="notes")
    assert card.status == notes.status == "refused" and "R4.value-shape" in rules(notes)
    assert world.dom("document.getElementById('cc').value + document.getElementById('notes').value") == ""
    assert CARD.replace(" ", "").encode() not in world.all_bytes()


@pytest.mark.parametrize("path", ["/captcha", "/challenge-403"])
def test_a_human_check_stops_the_step_pauses_the_origin_and_nothing_follows(world, site, path):
    world.nav("/notes")
    stopped = world.nav(path)
    assert stopped.status == "stopped" and stopped.verdict == "unverifiable"
    assert world.store.paused_targets() == frozenset({site.origin})
    calls = list(world.driver.calls)
    again = world.nav("/notes")
    assert again.status == "stopped" and "R2.paused" in rules(again)
    assert world.driver.calls == calls  # no retry, no route around the check


def test_submit_order_is_held_then_acts_once_after_a_console_approval(world, site):
    world.nav("/order")
    held = world.submit_order()
    assert held.status == "needs-human" and {"R7.irreversible"} <= rules(held) and site.orders == []
    assert not any(c.startswith("click") for c in world.driver.calls)
    authority_cli.main(["approve", "--state", str(world.store.path), "--approval-id", held.approval_id],
                       console=Console("click", site.origin.split("//")[1]))
    done = world.submit_order()
    assert (done.status, done.verdict) == ("acted", "verified") and len(site.orders) == 1
    world.nav("/order")
    assert world.submit_order().status == "needs-human" and len(site.orders) == 1  # single use


def test_an_injected_page_is_held_and_its_link_is_never_opened(world, site):
    assert world.nav("/reviews").status == "acted"
    result = world.nav("/wire-all-funds")
    assert result.status == "needs-human" and "R8.echo" in rules(result)
    assert ("GET", "/wire-all-funds") not in site.requests
    assert world.store.live_for(world.store.pending()[0]["step_digest"],
                                world.store.pending()[0]["before_digest"]) is None


def test_a_redirect_off_the_origin_is_refused_and_the_page_returns(world, site, other_site):
    site.redirect_to = other_site.url("/notes")
    world.nav("/notes")
    result = world.nav("/leave")
    assert result.status == "refused" and result.verdict == "not-acted"
    assert world.driver.current_url() == site.url("/notes")
    assert "off the allowed origins" in json.dumps(world.receipts.path.read_text(encoding="utf-8"))


def test_a_script_that_hides_the_automation_flag_is_refused(world):
    world.nav("/notes")
    result = world.step("hide", "browser.evaluate", "/notes",
                        args={"value": "Object.defineProperty(navigator, 'webdriver', {get: () => false})"},
                        post={"kind": "title_is", "value": "Notes"})
    assert result.status == "refused" and "R1.excluded" in rules(result)
    assert "evaluate" not in world.driver.calls and world.dom("navigator.webdriver") is True


def test_a_plain_script_is_held_as_irreversible(world):
    world.nav("/notes")
    result = world.step("title", "browser.evaluate", "/notes", args={"value": "document.title"},
                        post={"kind": "title_is", "value": "Notes"})
    assert result.status == "needs-human" and "R7.irreversible" in rules(result)
    assert "evaluate" not in world.driver.calls


def test_a_plan_runs_in_the_live_browser_and_certifies(world, site):
    plan = {"schema": "accountable-surface.action-plan/v1", "plan_id": "live", "steps": [
        {"step_id": "s1", "action_kind": "browser.navigate", "target": {"origin": site.origin, "path": "/notes"},
         "post_condition": {"kind": "url_is", "value": site.url("/notes")}},
        {"step_id": "s2", "action_kind": "browser.fill",
         "target": {"origin": site.origin, "path": "/notes", "control": {"name": "Body"}}, "args": {"value": "draft"},
         "post_condition": {"kind": "field_value_is", "control": {"name": "Body"}, "value": "draft"}},
        {"step_id": "s3", "action_kind": "browser.navigate", "target": {"origin": site.origin, "path": "/order"},
         "post_condition": {"kind": "url_is", "value": site.url("/order")}}]}
    result = world.pipe.run_plan(plan)
    assert [r.verdict for r in result.results] == ["verified"] * 3
    assert result.certificate["verdict"] == "verified"
