"""Post-condition predicates: pure functions of the after evidence.

Verdicts are typed: `verified` when the post-condition is settled true,
`drift` when it is settled false or a forbidden condition is present, and
`unverifiable` when nothing settles it. `unverifiable` is never rounded up.
"""

from __future__ import annotations

import builtins
import socket

import pytest

from accountable_surface import predicates
from accountable_surface.page_evidence import parse_page

DRIVER = {"url": "http://127.0.0.1:1/notes", "title": "Notes", "fields": {"Title": "weekly notes"}}


def _page(html, status=200):
    return parse_page("http://127.0.0.1:1/orders", html, http_status=status)


def _check(post, reader=None, driver=DRIVER):
    return predicates.check(post, driver_after=driver, reader_after=reader)[0]


def test_url_title_and_field_settle_from_the_driver_snapshot():
    assert _check({"kind": "url_is", "value": "http://127.0.0.1:1/notes/"}) == "verified"
    assert _check({"kind": "url_is", "value": "http://127.0.0.1:1/other"}) == "drift"
    assert _check({"kind": "title_is", "value": "Notes"}) == "verified"
    assert _check({"kind": "field_value_is", "control": {"name": "Title"}, "value": "weekly notes"}) == "verified"
    assert _check({"kind": "field_value_is", "control": {"name": "Title"}, "value": "other"}) == "drift"
    assert _check({"kind": "field_value_is", "control": {"name": "Gone"}, "value": "x"}) == "unverifiable"


def test_text_present_needs_a_settled_readback():
    assert _check({"kind": "text_present", "value": "Order 1"}, _page("<li>Order 1: quantity 1</li>")) == "verified"
    assert _check({"kind": "text_present", "value": "Order 2"}, _page("<li>Order 1</li>")) == "drift"
    assert _check({"kind": "text_present", "value": "Order 1"}, None) == "unverifiable"
    assert _check({"kind": "text_present", "value": "Order 1"}, _page("<li>Order 1</li>", 500)) == "unverifiable"


def test_element_presence_and_ambiguity():
    one = _page("<button>Saved</button>")
    two = _page("<button>Saved</button><button>Saved</button>")
    none = _page("<p>nothing</p>")
    post = {"kind": "element_appears", "control": {"name": "Saved"}}
    assert (_check(post, one), _check(post, none), _check(post, two)) == ("verified", "drift", "unverifiable")
    gone = {"kind": "element_disappears", "control": {"name": "Saved"}}
    assert (_check(gone, none), _check(gone, one), _check(gone, two)) == ("verified", "drift", "drift")


def test_forbidden_alert_is_drift():
    page = _page("<li>Order 1</li><div role='alert'>Payment failed</div>")
    post = {"kind": "text_present", "value": "Order 1", "forbid": [{"role": "alert"}]}
    assert _check(post, page) == "drift"
    assert _check({**post, "forbid": [{"text": "Payment failed"}]}, page) == "drift"
    assert _check(post, _page("<li>Order 1</li>")) == "verified"
    assert _check({"kind": "url_is", "value": DRIVER["url"], "forbid": [{"role": "alert"}]}, None) == "unverifiable"


def test_unknown_kind_is_unverifiable():
    assert _check({"kind": "region_changed"}) == "unverifiable"
    assert _check(None) == "unverifiable"


def test_meet_never_rounds_up():
    assert predicates.meet(["verified", "unverifiable"]) == "unverifiable"
    assert predicates.meet(["verified", "drift", "unverifiable"]) == "drift"
    assert predicates.meet(["verified", "verified"]) == "verified"
    assert predicates.meet([]) == "unverifiable"


def test_every_predicate_is_pure(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a predicate did I/O")

    page = _page("<button>Saved</button><li>Order 1</li>")
    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(socket, "socket", refuse)
    for post in ({"kind": "url_is", "value": "x"}, {"kind": "title_is", "value": "x"},
                 {"kind": "field_value_is", "control": {"name": "Title"}, "value": "x"},
                 {"kind": "text_present", "value": "Order 1"}, {"kind": "element_appears", "control": {"name": "Saved"}},
                 {"kind": "element_disappears", "control": {"name": "Saved"}}):
        assert _check(post, page) in ("verified", "drift", "unverifiable")


@pytest.mark.parametrize("kind", sorted(predicates.PREDICATES))
def test_every_registered_kind_is_one_the_plan_allows(kind):
    from accountable_surface.plan import CHECKABLE
    assert kind in CHECKABLE["web"] and kind in CHECKABLE["browser"]
