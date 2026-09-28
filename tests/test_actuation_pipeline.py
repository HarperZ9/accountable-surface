"""The accountable actuation pipeline against local pages on 127.0.0.1.

Negative controls, each refused or held for a person with a receipt saying why:
a password field, a card-number field, a fake CAPTCHA widget, a "Submit order"
button, and a page whose text tells the agent what to do. The positive control
is a plain fill on a notes page, which acts and verifies. Every step writes a
receipt. Nothing here reaches beyond 127.0.0.1.
"""

from __future__ import annotations

import json

import pytest
from actuation_site import Site

from accountable_surface import authority_cli
from accountable_surface.actuation_receipt import ReceiptLog, verify_chain
from accountable_surface.approvals import ApprovalStore
from accountable_surface.http_driver import HttpDriver
from accountable_surface.pipeline import ActuationPipeline
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import WebEffector

WEB_KINDS = ["web.navigate", "web.fill", "web.submit"]
CARD = "4111 1111 1111 1111"
PASSWORD = "hunter2-correct-horse-battery"


class SpyDriver(HttpDriver):
    """The real stdlib driver, counting every call that changes page state."""

    def __init__(self):
        super().__init__()
        self.mutating: list[str] = []

    def navigate(self, url):
        self.mutating.append(f"navigate {url}")
        super().navigate(url)

    def fill(self, selector, value):
        self.mutating.append(f"fill {selector}")
        super().fill(selector, value)

    def submit(self, url, data):
        self.mutating.append(f"submit {url}")
        super().submit(url, data)


class Console:
    def __init__(self, *answers):
        self.answers = list(answers)

    def show(self, text):
        pass

    def ask(self, prompt):
        return self.answers.pop(0)


def grant(origin, tier="full", **scope_extra):
    return {
        "authorization_version": "0.1", "receipt_id": "rcpt-actuation", "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"}, "agent": {"id": "pipeline-agent"},
        "intent": "local fixture actuation",
        "scope": {"allowed_actions": WEB_KINDS, "allowed_targets": [],
                  "target_tiers": [{"origin": origin, "tier": tier}], **scope_extra},
        "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00", "revoked": False,
    }


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


class World:
    def __init__(self, tmp_path, site, *, the_grant=None, driver=None):
        self.tmp, self.site = tmp_path, site
        self.driver = driver or SpyDriver()
        self.effector = WebEffector(self.driver, allowed_origins=[site.origin])
        self.store = ApprovalStore(tmp_path / "authority.db")
        self.receipts = ReceiptLog(tmp_path / "receipts.jsonl")
        self.surface = AccountableSurface(journal_path=tmp_path / "journal.jsonl")
        self.pipe = ActuationPipeline(self.surface, self.effector, grant=the_grant or grant(site.origin),
                                      approvals=self.store, receipts=self.receipts)

    def nav(self, path):
        return self.pipe.run_step({"step_id": f"nav{path}", "action_kind": "web.navigate",
                                   "target": {"origin": self.site.origin, "path": path},
                                   "post_condition": {"kind": "url_is", "value": self.site.url(path)}})

    def fill(self, path, name, value, sid="fill"):
        return self.pipe.run_step({"step_id": sid, "action_kind": "web.fill",
                                   "target": {"origin": self.site.origin, "path": path, "control": {"name": name}},
                                   "args": {"value": value},
                                   "post_condition": {"kind": "field_value_is", "control": {"name": name}, "value": value}})

    def submit_order(self):
        return self.pipe.run_step({
            "step_id": "submit", "action_kind": "web.submit",
            "target": {"origin": self.site.origin, "path": "/order", "control": {"name": "Submit order", "role": "button"}},
            "args": {"action": "/order/submit", "expect_title": "Order received"},
            "post_condition": {"kind": "text_present", "path": "/orders", "value": "Order 1: quantity 1"}})

    def receipt_lines(self):
        return [json.loads(line) for line in self.receipts.path.read_text(encoding="utf-8").splitlines()]

    def all_bytes(self):
        paths = [self.receipts.path, self.tmp / "journal.jsonl", self.store.path]
        return b"".join(p.read_bytes() for p in paths if p.exists())


def rules(result):
    return {h["rule"] for h in result.policy["rule_hits"]}


# --- positive control ---------------------------------------------------------

def test_benign_fill_on_a_local_page_acts_and_verifies(tmp_path, site):
    w = World(tmp_path, site)
    assert w.nav("/notes").verdict == "verified"
    result = w.fill("/notes", "Title", "weekly notes")
    assert (result.status, result.verdict) == ("acted", "verified")
    assert w.driver.field_value("Title") == "weekly notes"
    receipt = w.receipt_lines()[-1]
    assert receipt["step"]["value_hmac"].startswith("hmac-sha256:")
    assert receipt["verification"]["verdict"] == "verified" and receipt["execution"]["acted"] is True
    assert verify_chain(w.receipts.path)["verdict"] == "MATCH"


# --- negative controls ----------------------------------------------------------

def test_password_field_is_refused_with_a_receipt(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/login")
    calls = list(w.driver.mutating)
    result = w.fill("/login", "Password", PASSWORD)
    assert (result.status, result.verdict) == ("refused", "not-acted")
    assert "R4.secret-field" in rules(result)
    assert w.driver.mutating == calls and w.driver.field_value("Password") == ""
    receipt = w.receipt_lines()[-1]
    reasons = [h["reason"] for h in receipt["policy"]["rule_hits"]]
    assert any("type=password" in r for r in reasons) and receipt["step"]["value_hmac"] is None
    assert PASSWORD.encode() not in w.all_bytes() and PASSWORD not in result.message


def test_card_number_field_is_refused_with_a_receipt(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/checkout")
    calls = list(w.driver.mutating)
    result = w.fill("/checkout", "Card number", CARD)
    assert result.status == "refused" and {"R4.secret-field", "R4.value-shape"} <= rules(result)
    assert w.driver.mutating == calls
    notes = w.fill("/checkout", "Notes", CARD, sid="notes")
    assert notes.status == "refused" and rules(notes) == {"R4.value-shape"}
    assert CARD.encode() not in w.all_bytes() and CARD.replace(" ", "").encode() not in w.all_bytes()


def test_refused_value_never_persists_even_as_a_digest(tmp_path, site):
    """A digest of a short secret can be reversed by guessing, so a refused
    secret leaves no digest computed over it: not the step, plan, post-condition,
    or policy-inputs digest."""
    from accountable_surface import plan as plan_mod

    w = World(tmp_path, site)
    w.nav("/login")
    raw = {"step_id": "fill", "action_kind": "web.fill",
           "target": {"origin": site.origin, "path": "/login", "control": {"name": "Password"}},
           "args": {"value": PASSWORD},
           "post_condition": {"kind": "field_value_is", "control": {"name": "Password"}, "value": PASSWORD}}
    result = w.pipe.run_step(raw)
    step = plan_mod.step_from_dict(raw)
    stored = w.all_bytes()
    for digest in (plan_mod.step_digest(step), plan_mod.plan_digest([step]), plan_mod.digest(step.post_condition),
                   result.policy["inputs_digest"]):
        assert digest.split(":", 1)[1].encode() not in stored
    receipt = w.receipt_lines()[-1]
    assert receipt["step"]["withheld"] and receipt["policy"]["inputs_digest"] is None


def test_fake_captcha_in_the_before_evidence_stops_and_pauses(tmp_path, site):
    w = World(tmp_path, site)
    w.driver.navigate(site.url("/captcha"))  # the page is already on screen
    calls = list(w.driver.mutating)
    result = w.fill("/captcha", "Email", "ada@example.test")
    assert (result.status, result.verdict) == ("stopped", "not-acted")
    assert "R3.challenge" in rules(result) and "human check" in result.message
    assert w.driver.mutating == calls
    assert w.store.paused_targets() == frozenset({site.origin})
    assert w.receipt_lines()[-1]["before"]["detectors"]["challenge"]


def test_a_paused_target_refuses_every_next_step_with_no_request(tmp_path, site):
    w = World(tmp_path, site)
    w.driver.navigate(site.url("/captcha"))
    w.fill("/captcha", "Email", "ada@example.test")
    seen = len(site.requests)
    restarted = World(tmp_path, site)  # same state database, new process objects
    for step in (lambda: restarted.nav("/notes"), lambda: restarted.fill("/notes", "Title", "x")):
        result = step()
        assert result.status == "stopped" and "R2.paused" in rules(result)
    assert len(site.requests) == seen and restarted.driver.mutating == []


def test_challenge_raised_by_the_act_is_unverifiable_and_pauses(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    result = w.nav("/captcha")
    assert result.status == "stopped" and result.verdict == "unverifiable"
    assert w.store.paused_targets() == frozenset({site.origin})
    assert w.receipt_lines()[-1]["after"]["detectors"]["challenge"]


def test_http_challenge_status_stops_and_pauses(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    result = w.nav("/challenge-403")
    assert result.status == "stopped" and result.verdict == "unverifiable"
    assert w.store.paused_targets() == frozenset({site.origin})


def test_submit_order_is_held_for_a_person_then_acts_once_approved(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/order")
    held = w.submit_order()
    assert held.status == "needs-human" and held.approval_id and site.orders == []
    assert {"R7.irreversible"} <= rules(held)
    reasons = {h["reason"] for h in held.policy["rule_hits"]}
    assert {"effector:irreversible", "lexicon:submit", "structural:form-submit"} <= reasons
    assert "accountable-surface-authority approve" in held.message
    authority_cli.main(["approve", "--state", str(w.store.path), "--approval-id", held.approval_id,
                        "--approver", "operator"], console=Console("submit", site.origin.split("//")[1]))
    done = w.submit_order()
    assert (done.status, done.verdict) == ("acted", "verified") and len(site.orders) == 1
    receipt = w.receipt_lines()[-1]
    assert receipt["policy"]["approval"]["channel"] == "cli-tty"
    assert receipt["verification"]["independence"] == "separate-reader"


def test_grant_allow_irreversible_does_not_replace_confirmation(tmp_path, site):
    """A grant that says allow_irreversible is not read as a per-act approval.
    (proof-surface's closed schema would also deny such a grant at the gate, so
    the page is put on screen directly and the hold happens before the gate.)"""
    blanket = {**grant(site.origin), "allow_irreversible": True}
    w = World(tmp_path, site, the_grant=blanket)
    calls = []
    real = w.surface.actuate
    w.surface.actuate = lambda *a, **kw: calls.append(kw["allow_irreversible"]) or real(*a, **kw)
    w.driver.navigate(site.url("/order"))
    assert w.submit_order().status == "needs-human" and site.orders == [] and calls == []
    assert "allow_irreversible" not in ActuationPipeline.__init__.__code__.co_varnames


def test_approval_is_single_use_across_the_pipeline(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/order")
    held = w.submit_order()
    authority_cli.main(["approve", "--state", str(w.store.path), "--approval-id", held.approval_id],
                       console=Console("submit", site.origin.split("//")[1]))
    assert w.submit_order().status == "acted"
    w.nav("/order")
    again = w.submit_order()
    assert again.status == "needs-human" and len(site.orders) == 1


def test_injected_page_is_held_and_creates_and_consumes_no_approval(tmp_path, site):
    w = World(tmp_path, site)
    assert w.nav("/reviews").status == "acted"
    assert w.store.pending() == []
    result = w.nav("/wire-all-funds")
    assert result.status == "needs-human" and "R8.echo" in rules(result)
    [pending] = w.store.pending()
    assert pending["approval_id"] == result.approval_id
    assert any("ignore previous instructions" in s for s in pending["rendering"]["flagged_spans"])
    assert w.store.live_for(pending["step_digest"], pending["before_digest"]) is None
    assert ("GET", "/wire-all-funds") not in site.requests


def test_every_step_writes_a_receipt(tmp_path, site):
    w = World(tmp_path, site)
    results = [w.nav("/login"), w.fill("/login", "Password", PASSWORD), w.nav("/order"), w.submit_order(),
               w.fill("/order", "Quantity", "2", sid="qty")]
    assert [r.status for r in results] == ["acted", "refused", "acted", "needs-human", "acted"]
    lines = w.receipt_lines()
    assert len(lines) == len(results) + 1 and lines[0]["kind"] == "genesis"
    assert [ln["policy"]["outcome"] for ln in lines[1:]] == ["pass", "refuse", "pass", "confirm", "pass"]
    assert verify_chain(w.receipts.path)["verdict"] == "MATCH"


def test_malformed_step_is_refused_with_a_receipt(tmp_path, site):
    w = World(tmp_path, site)
    result = w.pipe.run_step({"step_id": "bad", "action_kind": "web.fill", "target": "http://127.0.0.1/x"})
    assert result.status == "refused" and "R9.schema" in rules(result)
    assert w.receipt_lines()[-1]["policy"]["outcome"] == "refuse" and site.requests == []
