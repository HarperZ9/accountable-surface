"""settle_ms: the readback waits for a post-condition that lands late (C9).

A post-condition may name `settle_ms`. The readback then re-reads until the
condition holds, a forbidden condition appears, or the time runs out. A timeout
is `unverifiable`, never a pass and never a settled drift, because nothing was
settled. The fixture's /status page shows "Saved" a set delay after /save-later
is opened. The stored after evidence records the timeout, so the verdict still
re-derives offline.
"""

from __future__ import annotations

import pytest
from actuation_site import Site
from actuation_world import World

from accountable_surface import predicates, rederive


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


def save_later(w, **post_extra):
    post = {"kind": "text_present", "path": "/status", "value": "Saved", **post_extra}
    w.pipe.run_step({"step_id": "open", "action_kind": "web.navigate",
                     "target": {"origin": w.site.origin, "path": "/notes"},
                     "post_condition": {"kind": "url_is", "value": w.site.url("/notes")}})
    step = {"step_id": "save", "action_kind": "web.navigate", "target": {"origin": w.site.origin, "path": "/save-later"},
            "post_condition": post}
    return w.pipe.run_step(step)


def test_without_settle_a_late_effect_reads_drift(tmp_path, site):
    result = save_later(World(tmp_path, site))
    assert result.verdict == "drift"


def test_settle_waits_for_a_late_effect_and_verifies(tmp_path, site):
    w = World(tmp_path, site)
    result = save_later(w, settle_ms=4000)
    assert result.verdict == "verified"
    assert sum(1 for method, path in site.requests if path == "/status") >= 2
    assert rederive.rederive(w.receipts.path, w.evidence.root)["verdict"] == "MATCH"


def test_a_timeout_is_unverifiable_and_re_derives(tmp_path, site):
    site.save_delay = 30
    w = World(tmp_path, site)
    result = save_later(w, settle_ms=300)
    assert result.verdict == "unverifiable" and "settle" in result.message
    assert rederive.rederive(w.receipts.path, w.evidence.root)["verdict"] == "MATCH"


def test_a_forbidden_condition_ends_the_wait_as_drift(tmp_path, site):
    w = World(tmp_path, site)
    result = save_later(w, settle_ms=4000, forbid=[{"text": "Working"}])
    assert result.verdict == "drift"
    assert sum(1 for method, path in site.requests if path == "/status") == 1


def test_timed_out_is_part_of_the_pure_predicate():
    post = {"kind": "text_present", "value": "Saved", "settle_ms": 100}
    assert predicates.check(post, driver_after={}, reader_after=None, timed_out=True)[0] == "unverifiable"
    assert predicates.check({"kind": "url_is", "value": "x"}, driver_after={"url": "y"}, reader_after=None,
                            timed_out=True)[0] == "unverifiable"
    assert predicates.check({"kind": "url_is", "value": "x"}, driver_after={"url": "x"}, reader_after=None,
                            timed_out=True)[0] == "verified"


def test_settle_ms_must_be_a_bounded_number(tmp_path, site):
    w = World(tmp_path, site)
    for bad in (-1, "soon", 600_001):
        result = save_later(w, settle_ms=bad)
        assert result.status == "refused" and "settle_ms" in result.message


def test_a_challenge_during_the_wait_stops_it_at_once(tmp_path, site):
    """Waiting on a page that turned into a human check would be retrying against
    it, so the wait ends on the first read that shows one, and the target pauses."""
    w = World(tmp_path, site)
    result = save_later(w, settle_ms=4000, path="/captcha")
    assert result.status == "stopped" and result.verdict == "unverifiable"
    assert sum(1 for method, path in site.requests if path == "/captcha") == 1
    assert w.store.paused_targets() == frozenset({site.origin})
