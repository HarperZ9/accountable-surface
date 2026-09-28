"""The verdict never reads the actor's own report, never rounds up, and a
rollback never changes it (I6, I7, S8).

- A driver that answers "done" and changes nothing reads drift, because the
  post-condition is settled by a separate read of the effect.
- An effector pass met with an unsettled readback is unverifiable, not verified.
- A reversible step that drifts is rolled back and read again; the verdict stays
  drift, and the receipt records the rollback beside it.
- An irreversible step is never rolled back by the pipeline, and an unverifiable
  one is not either: nothing settled that it went wrong.
"""

from __future__ import annotations

import pytest
from actuation_site import Site
from actuation_world import Console, SpyDriver, World

from accountable_surface import authority_cli, rederive


class ClaimsSubmitDriver(SpyDriver):
    """Says the order went through (the response title) and posts nothing."""

    def submit(self, url, data):
        self.mutating.append(f"submit {url}")
        self._title = "Order received"

    def snapshot(self):
        snap = super().snapshot()
        if getattr(self, "_title", None):
            snap["title"] = self._title
        return snap


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


def approve(w, approval_id):
    authority_cli.main(["approve", "--state", str(w.store.path), "--approval-id", approval_id],
                       console=Console("submit", w.site.origin.split("//")[1]))


def test_an_actor_that_claims_success_and_changes_nothing_reads_drift(tmp_path, site):
    w = World(tmp_path, site, driver=ClaimsSubmitDriver())
    w.nav("/order")
    approve(w, w.submit_order().approval_id)
    result = w.submit_order()
    receipt = w.receipt_lines()[-1]
    assert receipt["execution"]["surface_verdict"] == "pass"  # the actor's own check passed
    assert result.verdict == "drift" and site.orders == []
    assert receipt["verification"]["independence"] == "separate-reader"


def test_an_effector_pass_with_an_unsettled_readback_is_unverifiable(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    result = w.pipe.run_step({
        "step_id": "fill", "action_kind": "web.fill",
        "target": {"origin": site.origin, "path": "/notes", "control": {"name": "Title"}}, "args": {"value": "x"},
        "post_condition": {"kind": "text_present", "path": "/no-such-page", "value": "x"}})
    assert w.receipt_lines()[-1]["execution"]["surface_verdict"] == "pass"
    assert result.verdict == "unverifiable"


def forbidden_fill(w, site):
    return w.pipe.run_step({
        "step_id": "fill", "action_kind": "web.fill",
        "target": {"origin": site.origin, "path": "/notes", "control": {"name": "Title"}}, "args": {"value": "x"},
        "post_condition": {"kind": "field_value_is", "control": {"name": "Title"}, "value": "x", "path": "/notes",
                           "forbid": [{"text": "Scratch notes"}]}})


def test_a_drifted_reversible_step_is_rolled_back_and_stays_drift(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    result = forbidden_fill(w, site)
    receipt = w.receipt_lines()[-1]
    assert result.verdict == "drift" and receipt["verification"]["verdict"] == "drift"
    assert receipt["rollback"]["attempted"] is True and receipt["rollback"]["ok"] is True
    assert w.driver.field_value("Title") == ""  # the prior value is back
    assert rederive.rederive(w.receipts.path, w.evidence.root)["verdict"] == "MATCH"


def test_an_irreversible_drift_is_not_rolled_back(tmp_path, site):
    w = World(tmp_path, site, driver=ClaimsSubmitDriver())
    w.nav("/order")
    approve(w, w.submit_order().approval_id)
    calls = list(w.driver.mutating)
    assert w.submit_order().verdict == "drift"
    rollback = w.receipt_lines()[-1]["rollback"]
    assert rollback["attempted"] is False and "irreversible" in rollback["reason"]
    assert w.driver.mutating == calls + [f"submit {site.url('/order/submit')}"]


def test_an_unverifiable_step_is_not_rolled_back(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    w.pipe.run_step({
        "step_id": "fill", "action_kind": "web.fill",
        "target": {"origin": site.origin, "path": "/notes", "control": {"name": "Title"}}, "args": {"value": "x"},
        "post_condition": {"kind": "text_present", "path": "/no-such-page", "value": "x"}})
    assert w.receipt_lines()[-1]["rollback"] is None and w.driver.field_value("Title") == "x"


def test_a_verified_step_carries_no_rollback(tmp_path, site):
    w = World(tmp_path, site)
    w.nav("/notes")
    assert w.fill("/notes", "Title", "x").verdict == "verified"
    assert w.receipt_lines()[-1]["rollback"] is None
