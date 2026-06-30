"""Reference cortex -- runnable transcript: grounding, and admitting when it can't.

The organ returns witnessed, relevance-scored references for a subject -- and flags
'ungrounded' rather than surface an irrelevant citation. FakeSource here (offline,
deterministic); ArxivSource is the real native backend (stdlib urllib + xml).

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/grounding_demo.py
"""

from __future__ import annotations

from accountable_surface.reference import FakeSource, ReferenceCortex
from accountable_surface.surface import AccountableSurface

CORPUS = [
    {"source": "arxiv", "ref_id": "2401.0011",
     "title": "Accountable autonomy: gating and verification for language agents",
     "summary": "a pre-execution gate and post-action verification for agent actions",
     "url": "http://arxiv.org/abs/2401.0011"},
    {"source": "arxiv", "ref_id": "2312.0420",
     "title": "Provenance-bound perception for grounded reasoning",
     "summary": "witnessed observations with content-addressed provenance",
     "url": "http://arxiv.org/abs/2312.0420"},
    {"source": "arxiv", "ref_id": "2209.7777",
     "title": "A survey of sourdough fermentation",
     "summary": "baking bread at home", "url": "http://arxiv.org/abs/2209.7777"},
]


def main() -> None:
    cortex = ReferenceCortex(FakeSource(CORPUS))
    surface = AccountableSurface()

    for subject in ["accountable autonomy verification gating", "sourdough fermentation"]:
        print(f"== GROUND: {subject!r} ==")
        grounding = surface.ground(subject, cortex)
        print(f"  confidence: {grounding.confidence}   refs: {len(grounding.references)}   "
              f"digest: {grounding.digest[:23]}...")
        for ref in grounding.references:
            print(f"    - [{ref.relevance}] {ref.title}  ({ref.source}:{ref.ref_id})")
        print()

    print("== a subject with NO relevant corpus ==")
    grounding = surface.ground("orbital mechanics of trans-neptunian objects", cortex)
    print(f"  confidence: {grounding.confidence}   refs: {len(grounding.references)}   "
          "(the organ admits it cannot ground -- no laundered citation)\n")

    print("== JOURNAL (every grounding, witnessed) ==")
    for entry in surface.journal:
        if entry.kind == "grounding":
            print(f"  [{entry.kind}] {entry.summary}")


if __name__ == "__main__":
    main()
