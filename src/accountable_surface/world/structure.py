"""Structure -- the witnessed contour channel: where the form's edges are.

Lowers a decoded image to a luminance Field, traces iso-contours (marching
squares), stitches and simplifies them, and reports a re-derivable structure
reading: a contour count, an edge-ink measure, a legible outline, the simplified
polylines normalized to [0,1], and a ghash so structure is independently
re-checkable. Composes coherence-membrane organs; stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import math

from coherence_membrane.field import Field, FieldKind
from coherence_membrane.geometry_ops import contour, simplify_geometry, stitch

_TARGET_W = 128     # cap pure-Python contour cost; aspect preserved
_LEVEL = 0.5        # iso-level on luminance in [0,1]
_EPSILON = 0.75     # Douglas-Peucker tolerance, field-pixel space


def _luma_field(img, target_w: int = _TARGET_W) -> Field:
    """Box-average the image into a luminance Field (values [0,1]), capped to
    target_w wide, aspect preserved (min 1). Rec.601 luma; deterministic."""
    w, h = img.width, img.height
    tw = max(1, min(target_w, w))
    th = max(1, round(tw * h / w))
    ch, px = img.channels, img.pixels
    vals = []
    for ty in range(th):
        y0, y1 = ty * h // th, max(ty * h // th + 1, (ty + 1) * h // th)
        for tx in range(tw):
            x0, x1 = tx * w // tw, max(tx * w // tw + 1, (tx + 1) * w // tw)
            s = n = 0
            for yy in range(y0, y1):
                base = yy * w
                for xx in range(x0, x1):
                    i = (base + xx) * ch
                    if ch >= 3:
                        r, g, b = px[i], px[i + 1], px[i + 2]   # alpha (ch==4) ignored: luma only
                    else:
                        r = g = b = px[i]
                    s += 0.299 * r + 0.587 * g + 0.114 * b
                    n += 1
            vals.append((s / n) / 255.0 if n else 0.0)
    return Field(tw, th, FieldKind.LUMINANCE, tuple(vals), (False,) * (tw * th))


def _outline(n_contours: int, bbox, fw: int, fh: int) -> str:
    """A coarse, honest reading of where the traced structure sits."""
    if n_contours == 0 or bbox is None:
        return "no distinct edges"
    x0, y0, x1, y1 = bbox
    cx = ((x0 + x1) / 2) / max(fw - 1, 1)
    cy = ((y0 + y1) / 2) / max(fh - 1, 1)
    horiz = "left" if cx < 0.4 else "right" if cx > 0.6 else "centre"
    vert = "top" if cy < 0.4 else "bottom" if cy > 0.6 else "middle"
    where = "centred" if (horiz == "centre" and vert == "middle") else f"toward the {vert}-{horiz}"
    form = "a single traced contour" if n_contours == 1 else f"{n_contours} distinct contours"
    return f"{form}, {where}"


def witness_structure(img) -> dict:
    """Trace the edge structure of a decoded image into a re-derivable reading."""
    field = _luma_field(img)
    geo = simplify_geometry(stitch(contour(field, _LEVEL)), _EPSILON)
    fw, fh = field.width, field.height
    nx, ny = max(fw - 1, 1), max(fh - 1, 1)
    coords = [[[round(p.x / nx, 4), round(p.y / ny, 4)] for p in pl.points]
              for pl in geo.paths]
    ink = sum(math.hypot(a[0] - b[0], a[1] - b[1])
              for path in coords for a, b in zip(path, path[1:]))
    blob = json.dumps(coords, separators=(",", ":")).encode("utf-8")
    return {
        "contours": len(coords),
        "edge_ink": round(ink, 3),
        "outline": _outline(len(coords), geo.bbox(), fw, fh),
        "coords": coords,
        "ghash": hashlib.sha256(blob).hexdigest()[:16],
    }
