"""run_plan: a whole plan, in order, stopping at the first step not verified.

The plan document is validated before any step runs, so a malformed step three
never lets steps one and two act. Each receipt names the plan by an HMAC under
the session salt, so a later refused secret leaves no bare digest over itself in
an earlier receipt. The plan certificate is the lattice meet over every step,
steps that never ran included, so a worse step cannot be laundered.
"""

from __future__ import annotations

import pytest
from actuation_site import Site
from actuation_world import PASSWORD, SpyDriver, World

from accountable_surface import plan as plan_mod

SCHEMA = "accountable-surface.action-plan/v1"


class DroppedWriteDriver(SpyDriver):
    """Reports a fill as done and keeps nothing: the planted false success."""

    def fill(self, selector, value):
        self.mutating.append(f"fill {selector}")


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


def nav(site, sid, path):
    return {"step_id": sid, "action_kind": "web.navigate", "target": {"origin": site.origin, "path": path},
            "post_condition": {"kind": "url_is", "value": site.url(path)}}


def fill(site, sid, path, name, value):
    return {"step_id": sid, "action_kind": "web.fill",
            "target": {"origin": site.origin, "path": path, "control": {"name": name}},
            "args": {"value": value},
            "post_condition": {"kind": "field_value_is", "control": {"name": name}, "value": value}}


def plan(*steps, plan_id="plan-fixture"):
    return {"schema": SCHEMA, "plan_id": plan_id, "goal": "local fixture plan", "steps": list(steps)}


def five_steps(site):
    return plan(nav(site, "s1", "/notes"), fill(site, "s2", "/notes", "Title", "weekly notes"),
                fill(site, "s3", "/notes", "Body", "one"), nav(site, "s4", "/order"),
                fill(site, "s5", "/order", "Quantity", "2"))


def test_a_verified_plan_certifies_verified(tmp_path, site):
    w = World(tmp_path, site)
    result = w.pipe.run_plan(five_steps(site))
    assert [r.verdict for r in result.results] == ["verified"] * 5
    assert result.stopped_at is None and result.not_run == []
    assert result.certificate["verdict"] == "verified"


def test_false_success_at_step_two_stops_the_batch(tmp_path, site):
    w = World(tmp_path, site, driver=DroppedWriteDriver())
    result = w.pipe.run_plan(five_steps(site))
    assert [r.step_id for r in result.results] == ["s1", "s2"]
    assert result.results[1].verdict == "drift"
    assert result.stopped_at == "s2" and result.not_run == ["s3", "s4", "s5"]
    assert result.certificate["verdict"] != "verified"
    assert not any("Body" in call or "/order" in call for call in w.driver.mutating)
    assert len(w.receipt_lines()) == 1 + 2  # genesis and the two steps that ran


def test_a_held_step_stops_the_batch_and_the_certificate_is_not_verified(tmp_path, site):
    w = World(tmp_path, site)
    submit = {"step_id": "s2", "action_kind": "web.submit",
              "target": {"origin": site.origin, "path": "/order", "control": {"name": "Submit order", "role": "button"}},
              "args": {"action": "/order/submit", "expect_title": "Order received"},
              "post_condition": {"kind": "text_present", "path": "/orders", "value": "Order 1: quantity 1"}}
    result = w.pipe.run_plan(plan(nav(site, "s1", "/order"), submit, nav(site, "s3", "/notes")))
    assert [r.status for r in result.results] == ["acted", "needs-human"]
    assert result.not_run == ["s3"] and site.orders == []
    assert result.certificate["verdict"] == "unverifiable"


def test_a_malformed_step_anywhere_refuses_the_plan_before_any_act(tmp_path, site):
    w = World(tmp_path, site)
    bad = {"step_id": "s3", "action_kind": "web.fill", "target": "http://127.0.0.1/x"}
    result = w.pipe.run_plan(plan(nav(site, "s1", "/notes"), fill(site, "s2", "/notes", "Title", "x"), bad))
    assert [r.status for r in result.results] == ["refused"]
    assert "R9.schema" in {h["rule"] for h in result.results[0].policy["rule_hits"]}
    assert "s3" in result.results[0].message
    assert w.driver.mutating == [] and site.requests == []
    assert result.not_run == ["s1", "s2", "s3"] and result.certificate["verdict"] != "verified"


def test_a_plan_document_with_the_wrong_schema_is_refused(tmp_path, site):
    w = World(tmp_path, site)
    result = w.pipe.run_plan({"schema": "something-else/v9", "plan_id": "p", "steps": [nav(site, "s1", "/notes")]})
    assert [r.status for r in result.results] == ["refused"] and w.driver.mutating == []
    assert result.certificate["verdict"] != "verified"


def test_duplicate_step_ids_are_refused(tmp_path, site):
    w = World(tmp_path, site)
    result = w.pipe.run_plan(plan(nav(site, "s1", "/notes"), nav(site, "s1", "/order")))
    assert [r.status for r in result.results] == ["refused"] and w.driver.mutating == []


def test_receipts_name_the_plan_and_keep_no_bare_digest_over_a_later_secret(tmp_path, site):
    w = World(tmp_path, site)
    steps = [nav(site, "s1", "/login"), fill(site, "s2", "/login", "Email", "ada@example.test"),
             fill(site, "s3", "/login", "Password", PASSWORD)]
    result = w.pipe.run_plan(plan(*steps))
    assert [r.status for r in result.results] == ["acted", "acted", "refused"]
    receipts = w.receipt_lines()[1:]
    assert {r["step"]["plan_id"] for r in receipts} == {"plan-fixture"}
    refs = {r["step"]["plan_hmac"] for r in receipts[:2]}
    assert len(refs) == 1 and next(iter(refs)).startswith("hmac-sha256:")
    parsed = [plan_mod.step_from_dict(s) for s in steps]
    stored = w.all_bytes()
    for digest in (plan_mod.plan_digest(parsed), plan_mod.step_digest(parsed[2])):
        assert digest.split(":", 1)[1].encode() not in stored
    assert PASSWORD.encode() not in stored
    assert receipts[2]["step"]["plan_hmac"] is None and receipts[2]["step"]["withheld"]


def test_a_bare_list_of_steps_still_runs(tmp_path, site):
    w = World(tmp_path, site)
    result = w.pipe.run_plan([nav(site, "s1", "/notes"), fill(site, "s2", "/notes", "Title", "x")])
    assert [r.verdict for r in result.results] == ["verified", "verified"]
    assert result.certificate["verdict"] == "verified"
