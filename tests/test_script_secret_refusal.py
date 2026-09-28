"""A script cannot be a way around the secret refusal (R4 over browser.evaluate).

A fill into a password field is refused, so the same write through a script
must be too: a script that names a secret field together with a value read or
write, or that carries a secret-shaped literal, is refused before any driver
call. Reading a secret field's value is refused as well, because that hands a
secret a person typed back to the model. Benign scripts still pass R4 and stay
held as irreversible (R7).
"""

from __future__ import annotations

import pytest
from actuation_site import Site
from actuation_world import CARD

from accountable_surface import plan as plan_mod
from accountable_surface import policy
from accountable_surface.actuation_receipt import ReceiptLog
from accountable_surface.approvals import ApprovalStore
from accountable_surface.browser_effector import BrowserEffector, FakeBrowserDriver
from accountable_surface.detectors import secrets
from accountable_surface.evidence import EvidenceStore
from accountable_surface.page_evidence import parse_page
from accountable_surface.pipeline import ActuationPipeline
from accountable_surface.surface import AccountableSurface

ORIGIN = "http://127.0.0.1:9"
LOGIN = parse_page(ORIGIN + "/login", "<title>Sign in</title><label for='p'>Password</label>"
                   "<input id='p' name='password' type='password'>")
SECRET_SCRIPTS = [
    "document.getElementById('password').value = 'hunter2-correct-horse'",
    "document.querySelector('input[type=password]').value",
    "const f = document.querySelector('[name=cardnumber]'); f.value = '4000';",
    "document.querySelector('#cvv').setAttribute('value', '123')",
    "page.fill('#otp', '123456')",
    f"document.body.dataset.x = '{CARD}'",
    "fetch('/x', {headers: {Authorization: 'Bearer ghp_abcdefghijklmnopqrstuvwxyz0123'}})",
]
BENIGN_SCRIPTS = [
    "document.title",
    "window.scrollTo(0, 400)",
    "document.querySelector('#title').value",
    "document.querySelectorAll('li').length",
    "document.body.innerText.includes('Saved')",
]


def grant():
    kinds = ["browser.navigate", "browser.fill", "browser.click", "browser.evaluate"]
    return {"authorization_version": "0.1", "receipt_id": "rcpt-script", "kind": "authorization-grant",
            "principal": {"id": "operator-1", "role": "operator"}, "agent": {"id": "script-agent"},
            "intent": "script refusal fixture",
            "scope": {"allowed_actions": kinds, "allowed_targets": [],
                      "target_tiers": [{"origin": ORIGIN, "tier": "full"}]},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00", "revoked": False}


def script_step(script, origin=ORIGIN, path="/login"):
    return plan_mod.step_from_dict({"step_id": "js", "action_kind": "browser.evaluate",
                                    "target": {"origin": origin, "path": path}, "args": {"value": script},
                                    "post_condition": {"kind": "title_is", "value": "Sign in"}})


def decide(script):
    return policy.decide(script_step(script), LOGIN, grant=grant(), approval=None, paused=frozenset(),
                         now="2026-09-27T00:00:00+00:00", plan_reversible=False)


@pytest.mark.parametrize("script", SECRET_SCRIPTS)
def test_a_script_that_touches_a_secret_is_refused(script):
    decision = decide(script)
    assert decision.outcome == "refuse" and "R4.script" in {h["rule"] for h in decision.rule_hits}
    reasons = " ".join(h["reason"] for h in decision.rule_hits)
    assert "hunter2" not in reasons and CARD not in reasons and "ghp_" not in reasons


@pytest.mark.parametrize("script", BENIGN_SCRIPTS)
def test_a_benign_script_passes_r4_and_stays_held(script):
    decision = decide(script)
    rules = {h["rule"] for h in decision.rule_hits}
    assert not any(r.startswith("R4.") for r in rules) and decision.outcome == "confirm"


def test_the_script_rule_is_named_in_the_lexicon():
    assert secrets.lexicon()["script"]["write_markers"]


def test_the_pipeline_refuses_the_script_before_any_driver_call(tmp_path):
    site = Site().start()
    try:
        driver = FakeBrowserDriver(start=site.url("/login"))
        evaluated = []
        driver.evaluate = lambda script: evaluated.append(script)  # a spy on the one verb that runs code
        pipe = ActuationPipeline(AccountableSurface(journal_path=tmp_path / "j.jsonl"),
                                 BrowserEffector(driver, allowed_origins=[site.origin]),
                                 grant={**grant(), "scope": {**grant()["scope"], "target_tiers": [
                                     {"origin": site.origin, "tier": "full"}]}},
                                 approvals=ApprovalStore(tmp_path / "a.db"), receipts=ReceiptLog(tmp_path / "r.jsonl"),
                                 evidence=EvidenceStore(tmp_path / "ev"))
        result = pipe.run_step(script_step(SECRET_SCRIPTS[0], origin=site.origin).to_dict())
        assert result.status == "refused" and "R4.script" in {h["rule"] for h in result.policy["rule_hits"]}
        assert evaluated == []
        stored = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
        assert b"hunter2-correct-horse" not in stored
    finally:
        site.stop()
