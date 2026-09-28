"""Irreversible classification (R7) and money movement (R5), detector half.

Send, submit, publish, post, purchase, delete, and accept-terms controls are
classed irreversible, which holds the step for a person's confirmation. A form
submit is caught by structure even when its label is in another language. A
caller can raise the class and never lower it. Money movement (transfers,
trades, withdrawals) is not confirmable at all; the policy stops it.
"""

from __future__ import annotations

import pytest

from accountable_surface.detectors import irreversible
from accountable_surface.page_evidence import parse_page

IRREVERSIBLE = [
    "<button>Send</button>", "<button>Send message</button>", "<button>Submit</button>",
    "<button>Submit order</button>", "<button>Publish</button>", "<button>Save and publish</button>",
    "<button>Post</button>", "<button>Post comment</button>", "<button>Reply</button>",
    "<button>Share</button>", "<button>Buy now</button>", "<button>Purchase</button>",
    "<button>Pay $20.00</button>", "<button>Place order</button>", "<button>Proceed to checkout</button>",
    "<button>Check out</button>", "<button>Subscribe</button>", "<button>Donate</button>",
    "<button>Delete</button>", "<button>Delete file</button>", "<button>Yes, delete it</button>",
    "<button>Remove item</button>", "<button>Erase all data</button>", "<button>Discard draft</button>",
    "<button>Archive</button>", "<button>Accept all cookies</button>", "<button>I agree</button>",
    "<button>I accept the terms</button>", "<button>Agree and continue</button>", "<button>Consent</button>",
    "<button>Confirm</button>", "<button>Confirm purchase</button>", "<button>Sign document</button>",
    "<button>Close account</button>", "<button>Deactivate</button>", "<button>Unsubscribe</button>",
    "<button>Merge pull request</button>", "<button>Deploy</button>", "<button>Release</button>",
    "<button>Sign up</button>", "<button>Create account</button>", "<button>Register</button>",
    "<button>Authorize</button>", "<button>Allow</button>", "<a href='/delete/7'>Delete</a>",
    "<a href='/unsubscribe'>Unsubscribe</a>", "<input type='button' value='Empty trash'>",
]
NAVIGATION = [
    "<a href='/'>Home</a>", "<a href='/about'>About</a>", "<a href='/pricing'>Pricing</a>",
    "<a href='/docs'>Docs</a>", "<a href='/blog'>Blog</a>", "<a href='/orders'>Order history</a>",
    "<a href='/archive'>Archive</a>", "<a href='/releases'>Release notes</a>", "<a href='/posts'>Recent posts</a>",
    "<a href='/help'>Help</a>", "<a href='/contact'>Contact us</a>", "<a href='/p2'>Next page</a>",
    "<a href='/p0'>Previous</a>", "<a href='/settings'>Settings</a>", "<a href='/profile'>Profile</a>",
    "<a href='/login'>Sign in</a>", "<a href='/terms'>Terms of service</a>", "<a href='/privacy'>Privacy policy</a>",
    "<a href='/status'>Order status</a>", "<a href='/share'>Share feedback page</a>",
    "<button type='button'>Next</button>", "<button type='button'>Previous</button>",
    "<button type='button'>Show more</button>", "<button type='button'>Open menu</button>",
    "<button type='button'>Close</button>", "<button type='button'>Expand</button>",
    "<button type='button'>Collapse</button>", "<button type='button'>Sort by date</button>",
    "<button type='button'>Filter</button>", "<button type='button'>Search</button>",
    "<button type='button'>Back</button>", "<button type='button'>View details</button>",
    "<button type='button'>Read more</button>", "<button type='button'>Learn more</button>",
    "<button type='button'>Zoom in</button>", "<button type='button'>Play</button>",
    "<button type='button'>Pause</button>", "<button type='button'>Toggle theme</button>",
    "<button type='button'>Copy link</button>", "<button type='button'>Page 2</button>",
    "<button type='button'>Order history</button>", "<button type='button'>Show archive</button>",
]
FUNDS = ["Transfer funds", "Wire money", "Withdraw", "Withdraw to bank", "Buy shares",
         "Sell crypto", "Swap tokens", "Send money", "Trade", "Place trade"]


def _control(html, form=False):
    body = f"<form action='/x'>{html}</form>" if form else html
    return parse_page("http://127.0.0.1:1/p", body).controls[0]


def test_corpora_are_the_size_the_design_names():
    assert len(IRREVERSIBLE) >= 40 and len(NAVIGATION) >= 40


@pytest.mark.parametrize("html", IRREVERSIBLE)
def test_irreversible_corpus_all_confirm(html):
    control = _control(html)
    kind = "browser.click"
    assert irreversible.classify(kind, control, declared=False, plan_reversible=True), html


def test_navigation_corpus_escalates_at_most_5_percent():
    hits = [html for html in NAVIGATION
            if irreversible.classify("browser.click", _control(html), declared=False, plan_reversible=True)]
    assert len(hits) / len(NAVIGATION) <= 0.05, hits


def test_form_submit_caught_without_the_lexicon():
    for label in ("Absenden", "Enviar", "送信", "Weiter"):
        control = _control(f"<button>{label}</button>", form=True)
        assert "structural:form-submit" in irreversible.classify(
            "browser.click", control, declared=False, plan_reversible=True), label
    image = _control("<input type='image' alt='go'>", form=True)
    assert irreversible.classify("browser.click", image, declared=False, plan_reversible=True)


def test_type_button_in_a_form_is_not_a_submit():
    control = _control("<button type='button'>Weiter</button>", form=True)
    assert irreversible.classify("browser.click", control, declared=False, plan_reversible=True) == []


def test_declared_irreversible_raises_and_never_lowers():
    plain = _control("<button type='button'>Next</button>")
    assert irreversible.classify("browser.click", plain, declared=True, plan_reversible=True) == ["declared"]
    send = _control("<button>Send</button>")
    assert irreversible.classify("browser.click", send, declared=False, plan_reversible=True)


def test_effector_irreversible_kinds_are_classed_irreversible():
    for kind in ("web.submit", "browser.evaluate", "uia.invoke", "os.run"):
        assert "effector:irreversible" in irreversible.classify(kind, None, declared=False, plan_reversible=False)


def test_a_fill_is_not_classed_by_the_field_label():
    """Filling a field labelled "Post title" types text; it does not post."""
    field = _control("<label for='t'>Post title</label><input id='t'>")
    assert irreversible.classify("browser.fill", field, declared=False, plan_reversible=True) == []


@pytest.mark.parametrize("label", FUNDS)
def test_money_movement_is_recognised(label):
    assert irreversible.funds_move("browser.click", _control(f"<button>{label}</button>"), {}), label


def test_a_purchase_is_confirmable_not_a_money_movement():
    for label in ("Buy now", "Pay $20.00", "Place order", "Submit order", "Donate"):
        assert irreversible.funds_move("browser.click", _control(f"<button>{label}</button>"), {}) == [], label


def test_api_operation_names_count_for_money_movement():
    assert irreversible.funds_move("api.transfer_funds", None, {})
    assert irreversible.funds_move("api.create_issue", None, {}) == []
