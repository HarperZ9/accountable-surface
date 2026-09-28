"""The act binds to the state the policy saw (I5), and nothing that changes
state happens without a policy pass and a gate allow for this exact step (I1).
"""

from __future__ import annotations

from accountable_surface.actuation_receipt import ReceiptLog
from accountable_surface.approvals import ApprovalStore
from accountable_surface.page_evidence import parse_page
from accountable_surface.pipeline import ActuationPipeline
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import FakePageDriver, WebEffector

ORIGIN = "https://fixture.test"
URL = ORIGIN + "/notes"
HTML = "<title>Notes</title><form><label for='t'>Title</label><input id='t' name='title'></form>"


def _grant(tier="full", actions=("web.fill", "web.navigate", "web.submit")):
    return {"authorization_version": "0.1", "receipt_id": "r", "kind": "authorization-grant",
            "principal": {"id": "op", "role": "operator"}, "agent": {"id": "a"}, "intent": "t",
            "scope": {"allowed_actions": list(actions), "allowed_targets": [],
                      "target_tiers": [{"origin": ORIGIN, "tier": tier}]},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00", "revoked": False}


class CountingDriver(FakePageDriver):
    def __init__(self):
        super().__init__({URL: {"title": "Notes", "fields": {"Title": ""}}}, start=URL)
        self.mutating = []

    def fill(self, selector, value):
        self.mutating.append("fill")
        super().fill(selector, value)

    def navigate(self, url):
        self.mutating.append("navigate")
        super().navigate(url)

    def submit(self, url, data):
        self.mutating.append("submit")
        super().submit(url, data)


def _pipe(tmp_path, driver, reader, grant=None):
    effector = WebEffector(driver, allowed_origins=[ORIGIN])
    return ActuationPipeline(AccountableSurface(), effector, grant=grant or _grant(),
                             approvals=ApprovalStore(tmp_path / "a.db"),
                             receipts=ReceiptLog(tmp_path / "r.jsonl"), reader=reader)


def _fill(value="weekly notes", name="Title"):
    return {"step_id": "s1", "action_kind": "web.fill",
            "target": {"origin": ORIGIN, "path": "/notes", "control": {"name": name}},
            "args": {"value": value},
            "post_condition": {"kind": "field_value_is", "control": {"name": name}, "value": value}}


def test_state_change_between_policy_and_act_refuses(tmp_path):
    driver = CountingDriver()

    def reader(url):
        evidence = parse_page(url, HTML)
        driver.fill("Title", "someone else typed here")  # the page changes after S2
        return evidence

    result = _pipe(tmp_path, driver, reader).run_step(_fill())
    assert result.status == "refused" and result.verdict == "not-acted"
    assert driver.field_value("Title") == "someone else typed here"
    assert driver.mutating == ["fill"]  # only the change the test made


def test_unchanged_state_acts(tmp_path):
    driver = CountingDriver()
    result = _pipe(tmp_path, driver, lambda url: parse_page(url, HTML)).run_step(_fill())
    assert (result.status, result.verdict) == ("acted", "verified") and driver.mutating == ["fill"]


def test_no_mutating_driver_call_without_pass_and_allow(tmp_path):
    cases = [
        (_fill(value="4111 1111 1111 1111"), _grant(), HTML),                            # refuse (R4)
        (_fill(), _grant(), HTML + "<div class='cf-turnstile'></div>"),                    # stop (R3)
        (_fill(), _grant(tier="click"), HTML),                                             # refuse (R6)
        (_fill(name="Missing"), _grant(), HTML),                                           # refuse (R9)
        (_fill(), _grant(actions=("web.navigate",)), HTML),                                # gate deny
        ({**_fill(), "declared_irreversible": True}, _grant(), HTML),                      # confirm (R7)
    ]
    for index, (step, grant, html) in enumerate(cases):
        driver = CountingDriver()
        result = _pipe(tmp_path / str(index), driver, lambda url, h=html: parse_page(url, h), grant).run_step(step)
        assert result.status != "acted", (index, result.status)
        assert driver.mutating == [], (index, driver.mutating)


def test_reader_is_not_pointed_at_a_page_the_driver_is_not_on(tmp_path):
    driver, asked = CountingDriver(), []
    step = _fill()
    step["target"] = {"origin": "http://169.254.169.254", "path": "/latest", "control": {"name": "Title"}}
    result = _pipe(tmp_path, driver, lambda url: asked.append(url)).run_step(step)
    assert result.status == "refused" and asked == [] and driver.mutating == []
