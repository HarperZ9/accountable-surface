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
