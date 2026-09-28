"""Shared pieces for the pipeline tests: a spy on the real stdlib driver, a
scripted console for the approve CLI, a grant for the local fixture origin, and
a World that wires the pipeline to a fresh state database and receipt log.

Nothing here reaches beyond 127.0.0.1.
"""

from __future__ import annotations

import json

from accountable_surface.actuation_receipt import ReceiptLog
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
