"""Tests for the reference cortex -- a grounding organ (afferent, semantic).

Offline + deterministic via FakeSource. Proves: references are witnessed
(provenance digests), irrelevant sources are filtered, results are ranked, the
organ flags when it cannot ground (confidence), and the arXiv Atom parse is correct.
A grounding tool that can't admit "ungrounded" would launder falsehood.
"""

from __future__ import annotations

from accountable_surface.reference import FakeSource, ReferenceCortex, parse_arxiv_atom
from accountable_surface.surface import AccountableSurface


def test_grounds_a_relevant_subject_and_filters_the_irrelevant():
    source = FakeSource([
        {"source": "arxiv", "ref_id": "2401.1", "title": "Accountable autonomy in language agents",
         "summary": "gating and verification for agent actions", "url": "http://x/1"},
        {"source": "arxiv", "ref_id": "2401.2", "title": "Cooking pasta",
         "summary": "how to boil water", "url": "http://x/2"},
    ])
    grounding = ReferenceCortex(source).ground("accountable autonomy verification")
    titles = [r.title for r in grounding.references]
    assert "Accountable autonomy in language agents" in titles
    assert "Cooking pasta" not in titles  # irrelevant -> filtered out
    assert grounding.confidence in ("grounded", "weak")
    assert grounding.digest.startswith("sha256:")
    assert all(r.digest.startswith("sha256:") for r in grounding.references)  # every ref witnessed


def test_irrelevant_subject_is_ungrounded():
    source = FakeSource([
        {"source": "arxiv", "ref_id": "x", "title": "Cooking pasta", "summary": "boil water", "url": "u"},
    ])
    grounding = ReferenceCortex(source).ground("quantum gravity renormalization")
    assert grounding.confidence == "ungrounded"
    assert grounding.references == []  # the organ admits it could not ground


def test_references_ranked_by_relevance():
    source = FakeSource([
        {"source": "arxiv", "ref_id": "a", "title": "agent gating", "summary": "", "url": "u"},
        {"source": "arxiv", "ref_id": "b", "title": "agent gating verification accountability", "summary": "", "url": "u"},
    ])
    grounding = ReferenceCortex(source, min_relevance=0.0).ground("agent gating verification accountability")
    assert grounding.references[0].ref_id == "b"  # higher overlap ranks first


def test_max_refs_bounds_output():
    source = FakeSource([
        {"source": "arxiv", "ref_id": str(i), "title": "agent gating", "summary": "", "url": "u"} for i in range(10)
    ])
    grounding = ReferenceCortex(source, min_relevance=0.0, max_refs=3).ground("agent gating")
    assert len(grounding.references) == 3


def test_parse_arxiv_atom():
    xml = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        "<id>http://arxiv.org/abs/2401.12345v1</id>"
        "<title>A Title</title><summary>A summary.</summary>"
        "</entry></feed>"
    )
    refs = parse_arxiv_atom(xml)
    assert len(refs) == 1
    assert refs[0]["title"] == "A Title"
    assert "2401.12345" in refs[0]["ref_id"]


def test_selftest_holds():
    assert ReferenceCortex(FakeSource([])).selftest() is True


def test_surface_ground_journals_a_witnessed_grounding():
    source = FakeSource([
        {"source": "arxiv", "ref_id": "1", "title": "accountable agents gating", "summary": "", "url": "u"},
    ])
    surface = AccountableSurface()
    grounding = surface.ground("accountable agents gating", ReferenceCortex(source))
    assert grounding.confidence in ("grounded", "weak")
    assert any(e.kind == "grounding" for e in surface.journal)
