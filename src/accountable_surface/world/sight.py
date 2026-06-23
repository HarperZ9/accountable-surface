"""Witnessed sight — what the model actually sees when it looks at visual material.

Composes coherence-membrane's image organs into a richer, re-derivable perception so a text model
can discern and understand what's on screen:
  - SHAPE: an ASCII glyph grid (decode_png + ascii_view) — luminance, where the form is.
  - COLOUR: a compact spatial colour map (one letter per cell, with a legend) + the dominant
    colours, so the model knows WHICH colours sit WHERE — not just light and dark.
  - PROVENANCE: a perceptual hash + a content digest, so the sight is re-checkable, never faked.
The model reads all of it natively and cannot hallucinate it; a spectator sees the same grid.
Zero third-party deps (coherence-membrane is stdlib-only).
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path

from coherence_membrane.pngview import decode_png, is_png, read_ihdr
from coherence_membrane.ascii_view import ascii_view
from coherence_membrane.phash import perceptual_hash
from coherence_membrane.color import srgb_to_oklab, delta_e_ok
from .structure import witness_structure

_LEGEND = {"k": "dark", "w": "light", "n": "grey", "r": "red", "o": "orange",
           "y": "yellow", "g": "green", "c": "cyan", "b": "blue", "m": "purple"}

_BUSY_INK = 4.0   # "busy" vs "clean" edges: total contour length in normalized [0,1] frame units


# Seven chromatic anchors in OKLab (achromatic handled separately by L + chroma).
_ANCHORS = {ltr: srgb_to_oklab(rgb) for ltr, rgb in (
    ("r", (1.0, 0.0, 0.0)), ("o", (1.0, 0.5, 0.0)), ("y", (1.0, 1.0, 0.0)),
    ("g", (0.0, 1.0, 0.0)), ("c", (0.0, 1.0, 1.0)), ("b", (0.0, 0.0, 1.0)),
    ("m", (1.0, 0.0, 1.0)))}


def _classify(r, g, b) -> str:
    """One legend letter for a colour, OKLab-grounded. Dark/light/grey by OKLab
    lightness + chroma; otherwise the nearest chromatic anchor by delta_e_ok.
    r/g/b are 0-255 means. Perceptually-correct boundaries, re-derivable."""
    lab = srgb_to_oklab((r / 255.0, g / 255.0, b / 255.0))
    L, chroma = lab[0], math.hypot(lab[1], lab[2])
    if L < 0.30:
        return "k"
    if chroma < 0.04:
        return "w" if L > 0.85 else "n"
    return min(_ANCHORS, key=lambda k: delta_e_ok(lab, _ANCHORS[k]))


def _rgb_at(img, x, y):
    ch = img.channels
    i = (y * img.width + x) * ch
    px = img.pixels
    return (px[i], px[i + 1], px[i + 2]) if ch >= 3 else (px[i], px[i], px[i])


def _color_view(img, gc: int = 32, gr: int = 16) -> dict:
    """A coarse gc×gr colour map: each cell's mean colour as a legend letter, + the dominant mix."""
    w, h = img.width, img.height
    gc, gr = max(1, min(gc, w)), max(1, min(gr, h))
    grid, counts = [], Counter()
    lab_sums: dict = {}   # letter -> [sumL, suma, sumb, n]  (perceptual merge per legend bucket)
    for gy in range(gr):
        y0, y1 = gy * h // gr, max(gy * h // gr + 1, (gy + 1) * h // gr)
        ys = max(1, (y1 - y0) // 3)
        letters = []
        for gx in range(gc):
            x0, x1 = gx * w // gc, max(gx * w // gc + 1, (gx + 1) * w // gc)
            xs = max(1, (x1 - x0) // 3)
            r = g = b = n = 0
            for yy in range(y0, y1, ys):
                for xx in range(x0, x1, xs):
                    rr, gg, bb = _rgb_at(img, xx, yy)
                    r += rr; g += gg; b += bb; n += 1
            n = n or 1
            rm, gm, bm = r // n, g // n, b // n
            letter = _classify(rm, gm, bm)
            letters.append(letter); counts[letter] += 1
            lab = srgb_to_oklab((rm / 255.0, gm / 255.0, bm / 255.0))
            s = lab_sums.setdefault(letter, [0.0, 0.0, 0.0, 0])
            s[0] += lab[0]; s[1] += lab[1]; s[2] += lab[2]; s[3] += 1
        grid.append("".join(letters))
    total = sum(counts.values()) or 1
    palette = []
    for ltr, c in counts.most_common(5):
        s = lab_sums[ltr]
        palette.append({
            "name": _LEGEND[ltr], "pct": round(100 * c / total),
            "oklab": [round(s[0] / s[3], 3), round(s[1] / s[3], 3), round(s[2] / s[3], 3)],
        })
    legend = {ltr: _LEGEND[ltr] for ltr in sorted(set("".join(grid)))}
    return {"map": grid, "palette": palette, "legend": legend}


def witness_image(payload: bytes, *, cols: int = 96) -> dict:
    """A witnessed sight of a PNG: shape (glyph grid) + colour (spatial map + palette) + provenance."""
    w, h = read_ihdr(payload)[:2]   # cheap header read — refuse a decompression bomb before decode
    if w * h > 4_000_000:
        raise ValueError("image too large to witness")
    img = decode_png(payload)
    return {
        "kind": "image",
        "width": img.width,
        "height": img.height,
        "ascii": ascii_view(img, cols=cols),
        "color": _color_view(img),
        "structure": witness_structure(img),
        "phash": format(perceptual_hash(img), "016x"),
        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def describe_sight(sight) -> str:
    """A coarse, honest reading of the witnessed sight — shape, where the mass sits, and the colours.

    Not semantic understanding: brightness coverage + where the bright mass sits + the dominant
    colours, each re-derivable from the same sight the model and spectator share. Cites the phash so
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
    pal = (sight.get("color") or {}).get("palette") or []
    colour = ("; colours: " + ", ".join(f"{p['name']} {p['pct']}%" for p in pal[:3])) if pal else ""
    st = sight.get("structure") or {}
    nc = st.get("contours", 0)
    busy = "clean edges" if st.get("edge_ink", 0.0) < _BUSY_INK else "busy edges"
    structure = f"; {nc} contour{'s' if nc != 1 else ''}, {busy}" if st else ""
    return (f"{shape}, about {int(round(coverage * 100))}% bright, toward {where}{colour}"
            f"{structure}; {w}×{h} glyph grid, phash {sight.get('phash')}")


_CACHE: dict = {}   # (path, size, mtime, cols) -> sight; keeps the richer sight cheap on re-snapshot


def sight_of(path, *, cols: int = 96) -> dict | None:
    """Witness an image file as sight; None if it isn't a decodable image (can't see != lying)."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_size, int(st.st_mtime), cols)
    if key in _CACHE:
        return _CACHE[key]
    try:
        payload = p.read_bytes()
    except OSError:
        return None
    if not is_png(payload):
        return None
    try:
        sight = {"name": p.name, **witness_image(payload, cols=cols)}
    except Exception:
        return None  # an undecodable/oddball PNG: we honestly can't see it, we don't pretend to
    if len(_CACHE) > 64:
        _CACHE.pop(next(iter(_CACHE)))   # evict the oldest one, not the whole cache
    _CACHE[key] = sight
    return sight
