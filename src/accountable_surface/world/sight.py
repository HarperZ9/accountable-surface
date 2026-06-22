"""Witnessed sight — what the model actually sees when it looks at visual material.

Composes coherence-membrane's image organs: an image becomes a faithful, re-derivable ASCII glyph
grid (decode_png + ascii_view) plus a perceptual hash and a content digest. The model reads the
glyph grid natively and cannot hallucinate it; a spectator watching sees the SAME grid — the
shared sight. This is the anti-blind organ: the body hands the mind real perception, not a guess.
Zero third-party deps (coherence-membrane is stdlib-only).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from coherence_membrane.pngview import decode_png, is_png
from coherence_membrane.ascii_view import ascii_view
from coherence_membrane.phash import perceptual_hash


def witness_image(payload: bytes, *, cols: int = 48) -> dict:
    """A witnessed sight of a PNG: the glyph grid the model sees + a re-derivable digest + phash."""
    img = decode_png(payload)
    return {
        "kind": "image",
        "width": img.width,
        "height": img.height,
        "ascii": ascii_view(img, cols=cols),
        "phash": format(perceptual_hash(img), "016x"),
        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def describe_sight(sight) -> str:
    """A coarse, honest reading of the witnessed glyph grid — only what the grid itself shows.

    Not semantic understanding: brightness coverage + where the bright mass sits + a compact-vs-broad
    guess, each re-derivable from the same grid the model and spectator both see. Cites the phash so
    the reading is anchored to the witnessed image, not asserted out of thin air.
    """
    rows = sight.get("ascii", [])
    bright = total = sx = sy = n = 0
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            total += 1
            if c not in " .:":              # space/dot/colon are the dark end of the ramp
                bright += 1
                sx += x; sy += y; n += 1
    total = total or 1
    coverage = bright / total
    w = len(rows[0]) if rows else 1
    h = len(rows) or 1
    cx = (sx / n) / w if n else 0.5
    cy = (sy / n) / h if n else 0.5
    horiz = "left" if cx < 0.4 else "right" if cx > 0.6 else "centre"
    vert = "top" if cy < 0.4 else "bottom" if cy > 0.6 else "middle"
    where = "the centre" if (horiz == "centre" and vert == "middle") else f"the {vert}-{horiz}"
    shape = "a mostly dark field" if bright == 0 else (
        "a compact bright region" if coverage < 0.45 else "a broad bright field")
    return (f"{shape}, about {int(round(coverage * 100))}% bright, toward {where}; "
            f"{w}×{h} glyph grid, phash {sight.get('phash')}")


def sight_of(path, *, cols: int = 48) -> dict | None:
    """Witness an image file as sight; None if it isn't a decodable image (can't see != lying)."""
    p = Path(path)
    try:
        payload = p.read_bytes()
    except OSError:
        return None
    if not is_png(payload):
        return None
    try:
        return {"name": p.name, **witness_image(payload, cols=cols)}
    except Exception:
        return None  # an undecodable/oddball PNG: we honestly can't see it, we don't pretend to
