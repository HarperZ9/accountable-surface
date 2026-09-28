"""A CAPTCHA or bot check on screen makes the tool stop.

Detector half: every challenge fixture is recognised, benign pages close to them
are not, and no fixture reaches off the machine. The pipeline half (the stop
itself, the pause, no driver call after it) is in test_actuation_pipeline.py.
"""

from __future__ import annotations

import re
import socket

import pytest
from actuation_corpus import BENIGN_PAGES, CHALLENGE_PAGES

from accountable_surface.detectors import challenge
from accountable_surface.page_evidence import PageEvidence, parse_page


def _evidence(html, status=200, headers=None):
    return parse_page("http://127.0.0.1:1/page", html, http_status=status, response_headers=headers)


def test_corpora_are_the_size_the_design_names():
    assert len(CHALLENGE_PAGES) >= 20 and len(BENIGN_PAGES) >= 100


@pytest.mark.parametrize("label,html,status,headers", CHALLENGE_PAGES, ids=[c[0] for c in CHALLENGE_PAGES])
def test_marker_fixtures_all_stop(label, html, status, headers):
    assert challenge.scan(_evidence(html, status, headers)), label


def test_benign_fixtures_false_stops_at_most_2_percent():
    false_stops = [label for label, html, status, headers in BENIGN_PAGES
                   if challenge.scan(_evidence(html, status, headers))]
    assert len(false_stops) / len(BENIGN_PAGES) <= 0.02, false_stops


def test_fixtures_load_no_external_script():
    remote = re.compile(r"""(src|href|action)\s*=\s*['"]?\s*(https?:)?//""", re.I)
    for label, html, _, _ in CHALLENGE_PAGES + BENIGN_PAGES:
        assert not remote.search(html), label
        assert "<script" not in html.lower(), label


def test_provider_frame_source_is_recognised():
    """Built as evidence, not as a fixture page, so no file carries a remote src."""
    evidence = PageEvidence(url="http://127.0.0.1:1/x", http_status=200, headers=(), title="Pay",
                            controls=(), frames=(("https://www.google.com/recaptcha/api2/anchor?k=x", ""),),
                            markers=(), text="")
    assert [h.marker for h in challenge.scan(evidence)] == ["google.com/recaptcha"]


def test_status_alone_is_not_a_challenge():
    """A plain 403 or 429 is refusal or rate limit, not a challenge; the header decides."""
    assert challenge.scan(_evidence("<p>no</p>", 403, {})) == ()
    assert challenge.scan(_evidence("", 403, {"cf-mitigated": "challenge"}))


def test_scan_reads_and_never_reaches_the_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the detector opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    label, html, status, headers = CHALLENGE_PAGES[0]
    assert challenge.scan(_evidence(html, status, headers))


def test_lexicon_names_every_marker_set():
    lex = challenge.lexicon()
    assert set(lex) == {"version", "providers", "markers", "frame_titles", "title_only", "phrases", "statuses"}
    assert "i'm not a robot" in lex["phrases"] and "g-recaptcha" in lex["markers"]
