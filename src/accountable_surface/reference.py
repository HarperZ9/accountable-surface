"""The reference cortex -- a grounding organ (afferent, semantic).

Given a subject, it returns WITNESSED references (provenance-bound, relevance-scored),
never raw assertions. A grounding tool that surfaces plausible-but-irrelevant sources
launders falsehood with the authority of a citation -- so this organ witnesses every
reference, scores relevance natively (lexical overlap -- explainable, no ML, no external
deps), flags when it cannot ground (`confidence`), and stays INERT (it grounds; it
asserts nothing).

Native: a `source` abstraction. `FakeSource` (offline tests) and `ArxivSource` (real,
stdlib `urllib` + `xml.etree`). The relevance scoring and the Atom parse are tested;
the network fetch is a thin, labeled wrapper.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from coherence_membrane.observation import sha256_hex

_WORD = re.compile(r"[a-z0-9]+")
_ATOM = "{http://www.w3.org/2005/Atom}"


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def _relevance(subject: str, text: str) -> float:
    """Fraction of the subject's significant terms present in the text (0..1).
    Crude and lexical by design -- explainable, never a confident black box."""
    subject_terms = _tokens(subject)
    if not subject_terms:
        return 0.0
    return len(subject_terms & _tokens(text)) / len(subject_terms)


@dataclass(frozen=True)
class Reference:
    source: str
    ref_id: str
    title: str
    summary: str
    url: str
    relevance: float
    digest: str  # content-address of the reference


@dataclass(frozen=True)
class Grounding:
    """A witnessed grounding result for a subject."""

    subject: str
    references: list
    confidence: str  # "grounded" | "weak" | "ungrounded"
    digest: str


def parse_arxiv_atom(xml: str) -> list[dict]:
    """Parse an arXiv Atom feed into reference dicts (stdlib only)."""
    root = ET.fromstring(xml)
    out: list[dict] = []
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        ref_id = entry_id.rsplit("/abs/", 1)[-1] if "/abs/" in entry_id else entry_id
        out.append({
            "source": "arxiv",
            "ref_id": ref_id,
            "title": " ".join((entry.findtext(f"{_ATOM}title") or "").split()),
            "summary": " ".join((entry.findtext(f"{_ATOM}summary") or "").split()),
            "url": entry_id,
        })
    return out


class FakeSource:
    """Deterministic source for tests/offline demos -- canned result dicts."""

    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return list(self._results)[:limit]


class ArxivSource:
    """Real source -- the arXiv API over stdlib urllib (http/https). Network; the PARSE
    is tested (`parse_arxiv_atom`), this thin fetch wrapper is not exercised offline."""

    def __init__(self, *, timeout: float = 10.0, max_bytes: int = 5_000_000) -> None:
        self._timeout = timeout
        self._max = max_bytes

    def search(self, query: str, limit: int = 10) -> list[dict]:
        params = urllib.parse.urlencode({"search_query": f"all:{query}", "max_results": int(limit)})
        url = f"http://export.arxiv.org/api/query?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "accountable-surface/0.1 (native)"})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 (https/http literal)
            payload = response.read(self._max + 1)[: self._max]
        return parse_arxiv_atom(payload.decode("utf-8", errors="replace"))


class ReferenceCortex:
    """Grounds a subject in witnessed, relevance-scored references. Inert."""

    name = "reference-cortex"

    def __init__(self, source, *, min_relevance: float = 0.3, max_refs: int = 5) -> None:
        self._source = source
        self._min = min_relevance
        self._max = max_refs

    def ground(self, subject: str) -> Grounding:
        raw = self._source.search(subject, limit=max(self._max * 3, 10))
        scored = []
        for item in raw:
            relevance = _relevance(subject, f"{item.get('title', '')} {item.get('summary', '')}")
            if relevance >= self._min:
                scored.append(self._witness(item, relevance))
        scored.sort(key=lambda r: r.relevance, reverse=True)
        scored = scored[: self._max]
        top = scored[0].relevance if scored else 0.0
        confidence = "grounded" if top >= 0.6 else ("weak" if scored else "ungrounded")
        body = ";".join(f"{r.source}|{r.ref_id}|{r.relevance}" for r in scored)
        digest = "sha256:" + sha256_hex(f"{subject}=>{body}".encode("utf-8"))
        return Grounding(subject, scored, confidence, digest)

    def selftest(self) -> bool:
        """Falsifiable: a source with no relevant material must yield 'ungrounded',
        not a confident-looking citation."""
        probe = ReferenceCortex(
            FakeSource([{"source": "x", "ref_id": "1", "title": "zzz qqq", "summary": "", "url": ""}])
        )
        return probe.ground("entirely unrelated subject terms").confidence == "ungrounded"

    def _witness(self, item: dict, relevance: float) -> Reference:
        source = item.get("source", "")
        ref_id = item.get("ref_id", "")
        title = item.get("title", "")
        digest = "sha256:" + sha256_hex(f"{source}|{ref_id}|{title}".encode("utf-8"))
        return Reference(source, ref_id, title, item.get("summary", ""), item.get("url", ""), round(relevance, 3), digest)
