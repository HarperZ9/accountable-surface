# Bilateral Eye -- Increment 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the witnessed sight a structure (contour) channel and OKLab-grounded colour, and draw the same contours + colour the model reads into the spectator view -- the bilateral "same frame" in one increment.

**Architecture:** A new pure lowering module (`world/structure.py`) traces an image's edges via coherence-membrane's marching-squares `contour` → `stitch` → `simplify`, normalized to [0,1]. `world/sight.py` composes it into the sight and swaps the hand-rolled HSV colour for OKLab nearest-anchor classification with a perceptually-merged palette. The frontend gains a pure, node-tested coord-mapping module (`web/overlay.js`) and draws contours on the existing image canvas plus an OKLab colour map.

**Tech Stack:** Python 3 (stdlib only; coherence-membrane is the sole import, itself stdlib-only). Vanilla ES-module JavaScript for the browser. `pytest` for Python, `node --test` for the frontend, Playwright for one visual confirmation.

## Global Constraints

- **Zero third-party deps.** Python imports only stdlib + `coherence_membrane`. Frontend is vanilla JS, no framework.
- **Fail-closed perception.** Never omit a channel or fabricate data. "Can't see X" is reported honestly (e.g. `contours: 0`, `outline: "no distinct edges"`), never faked.
- **Re-derivable.** Everything in the sight derives deterministically from the same `payload`; the image `digest` covers it and `structure.ghash` makes structure independently re-checkable.
- **Legend stays the 10 existing letters** (`k w n r o y g c b m`) so existing tests/legend hold.
- **File size:** keep files focused; `sight.py` and `structure.py` each under 300 lines, functions under 50 lines.
- **Testing:** targeted slice only (`tests/test_sight.py` + world-server tests + the frontend node test); no full-suite run unless asked.
- **Coordinate convention:** cm geometry coords are field-pixel space (x right, y down). Normalize by `max(fieldW-1, 1)` / `max(fieldH-1, 1)` → `[0,1]`.

### cm organ signatures this plan consumes (verbatim)

- `coherence_membrane.pngview.decode_png(payload) -> img` with `img.width, img.height, img.channels, img.pixels` (bytes, row-major, `channels` per pixel).
- `coherence_membrane.field.Field(width, height, kind, values: tuple[float,...], unknown: tuple[bool,...])`; `coherence_membrane.field.FieldKind.LUMINANCE` (values in [0,1]).
- `coherence_membrane.geometry_ops.contour(field, level=0.5) -> Geometry`
- `coherence_membrane.geometry_ops.stitch(geometry) -> Geometry`
- `coherence_membrane.geometry_ops.simplify_geometry(geometry, epsilon) -> Geometry`
- `Geometry.paths: tuple[Polyline,...]`, `Geometry.bbox() -> (x0,y0,x1,y1) | None`; `Polyline.points: tuple[Point,...]`; `Point.x, Point.y`.
- `coherence_membrane.color.srgb_to_oklab(rgb: tuple[float,float,float]) -> (L,a,b)` (rgb gamma, [0,1]).
- `coherence_membrane.color.delta_e_ok(lab1, lab2) -> float`.

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `src/accountable_surface/world/structure.py` | Create | Image → luminance Field → contour → stitch → simplify → normalized structure reading (`contours`, `edge_ink`, `outline`, `coords`, `ghash`). Pure, deterministic. |
| `src/accountable_surface/world/sight.py` | Modify | Add `structure` to `witness_image`; replace HSV `_classify` with OKLab; add mean-OKLab to palette; extend `describe_sight` to read structure. |
| `tests/test_sight.py` | Modify | New tests for structure + OKLab + describe_sight + parity. |
| `web/overlay.js` | Create | Pure `normToCanvas(coords, w, h)` + `drawContours(ctx, coords, w, h, opts)` + `LETTER_CSS`/`renderColorMap`. ES module; also attaches to `window` for the browser. |
| `web/overlay.test.mjs` | Create | `node --test` gate for `normToCanvas` coord math. |
| `web/together.html` | Modify | Add `<canvas id="overlay">` over the photo, a `#color-map` panel, and `<script type="module" src="overlay.js">`. |
| `web/together.js` | Modify | In `showOverlay`, draw contours on the overlay canvas and render the colour map. |

---

## Task 1: `structure.py` -- the contour lowering

**Files:**
- Create: `src/accountable_surface/world/structure.py`
- Test: `tests/test_sight.py` (new tests appended)

**Interfaces:**
- Consumes: cm `decode_png`, `Field`, `FieldKind`, `contour`, `stitch`, `simplify_geometry` (signatures above).
- Produces: `witness_structure(img) -> dict` with keys `contours: int`, `edge_ink: float`, `outline: str`, `coords: list[list[list[float]]]` (polylines of `[x,y]` in [0,1]), `ghash: str` (16 hex chars). `img` is a decoded image (the `DecodedImage` from `decode_png`), NOT raw bytes -- `sight.py` already decodes once and passes it in.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sight.py`:

```python
from coherence_membrane.pngview import decode_png
from accountable_surface.world.structure import witness_structure


def test_structure_traces_a_disc_outline():
    st = witness_structure(decode_png(_disc_png()))
    assert st["contours"] >= 1                       # the disc has an edge
    assert "centred" in st["outline"]                # and it sits in the centre
    assert st["coords"] and all(                      # coords normalized to [0,1]
        0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        for path in st["coords"] for x, y in path)
    assert len(st["ghash"]) == 16


def test_structure_of_a_flat_image_is_honestly_empty():
    flat = encode_png(16, 16, bytes([128, 128, 128]) * (16 * 16), channels=3)
    st = witness_structure(decode_png(flat))
    assert st["contours"] == 0                        # no edges -- and we say so
    assert st["outline"] == "no distinct edges"
    assert st["coords"] == []
    assert len(st["ghash"]) == 16                     # key present, never omitted


def test_structure_ghash_is_deterministic():
    a = witness_structure(decode_png(_disc_png()))
    b = witness_structure(decode_png(_disc_png()))
    assert a["ghash"] == b["ghash"] and a["coords"] == b["coords"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sight.py -k structure -v`
Expected: FAIL with `ModuleNotFoundError: accountable_surface.world.structure`.

- [ ] **Step 3: Write `structure.py`**

```python
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
                        r, g, b = px[i], px[i + 1], px[i + 2]
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
    form = "a single closed form" if n_contours == 1 else f"{n_contours} distinct contours"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sight.py -k structure -v`
Expected: PASS (3 tests). If `test_structure_traces_a_disc_outline` finds `contours == 0`, the disc PNG is too small for the 128-wide field to resolve -- it won't be; `_disc_png()` is 40×40 and the level-0.5 crossing on the bright disc vs dark field yields a closed loop.

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/structure.py tests/test_sight.py
git commit -m "feat(world): witness the edge structure of an image (contour channel)"
```

---

## Task 2: OKLab colour in `sight.py`

**Files:**
- Modify: `src/accountable_surface/world/sight.py` (replace `_classify`; extend `_color_view` palette)
- Test: `tests/test_sight.py`

**Interfaces:**
- Consumes: cm `srgb_to_oklab`, `delta_e_ok`.
- Produces: `_classify(r, g, b) -> str` (same 10-letter contract, r/g/b are 0--255 ints) now OKLab-grounded; `_color_view(...)` palette entries gain `"oklab": [L, a, b]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sight.py`:

```python
def test_colour_is_oklab_grounded_and_palette_carries_oklab():
    s = witness_image(_split_png((220, 40, 40), (40, 180, 70)), cols=24)  # red / green
    names = " ".join(p["name"] for p in s["color"]["palette"])
    assert "red" in names and "green" in names               # still perceives the colours
    for p in s["color"]["palette"]:
        assert "oklab" in p and len(p["oklab"]) == 3          # each entry carries OKLab


def test_palette_merges_near_identical_shades_into_one_entry():
    # two near-identical reds top, green bottom: the reds collapse to a single 'red' entry
    s = witness_image(_split_png((210, 30, 30), (40, 180, 70)), cols=24)
    reds = [p for p in s["color"]["palette"] if p["name"] == "red"]
    assert len(reds) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sight.py -k "oklab or merges" -v`
Expected: FAIL -- `KeyError: 'oklab'` (palette entries have no `oklab` key yet).

- [ ] **Step 3: Replace `_classify` and extend `_color_view`**

In `sight.py`, update the imports near the top (add the colour organ):

```python
from coherence_membrane.color import srgb_to_oklab, delta_e_ok
```

Replace the whole `_classify` function with the OKLab version:

```python
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
```

Add `import math` at the top if not already present (it is not in the current file -- add it beside `import hashlib`).

In `_color_view`, accumulate mean OKLab per letter and emit it in the palette. Replace the cell loop's per-cell tail and the palette construction:

```python
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
```

- [ ] **Step 4: Run the colour tests + the existing colour test**

Run: `python -m pytest tests/test_sight.py -k "oklab or merges or colour or palette" -v`
Expected: PASS, including the pre-existing `test_witnessed_sight_includes_colour_palette_and_spatial_map`.

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/sight.py tests/test_sight.py
git commit -m "feat(world): OKLab-grounded colour + perceptually-merged palette"
```

---

## Task 3: Compose structure into the sight + the honest reading

**Files:**
- Modify: `src/accountable_surface/world/sight.py` (`witness_image`, `describe_sight`)
- Test: `tests/test_sight.py`

**Interfaces:**
- Consumes: `witness_structure` (Task 1), the decoded `img` already built in `witness_image`.
- Produces: `witness_image(...)` result gains `"structure"`; `describe_sight(sight)` mentions contour count.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sight.py`:

```python
def test_witnessed_sight_includes_the_structure_channel():
    s = witness_image(_disc_png(), cols=32)
    assert "structure" in s
    assert s["structure"]["contours"] >= 1
    assert "coords" in s["structure"] and "ghash" in s["structure"]


def test_describe_sight_reads_structure():
    desc = describe_sight(witness_image(_disc_png(), cols=32))
    assert "contour" in desc.lower()     # it names the structure it traced
    assert "phash" in desc               # still anchored to the witnessed phash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sight.py -k "structure_channel or reads_structure" -v`
Expected: FAIL -- `KeyError: 'structure'` and the description lacks "contour".

- [ ] **Step 3: Wire structure in**

In `sight.py`, add the import:

```python
from .structure import witness_structure
```

In `witness_image`, add `structure` to the returned dict (the `img` is already decoded there):

```python
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
```

In `describe_sight`, build a structure clause and insert it before the grid clause. Add, after the `colour = ...` line:

```python
    st = sight.get("structure") or {}
    nc = st.get("contours", 0)
    busy = "clean edges" if st.get("edge_ink", 0.0) < 4.0 else "busy edges"
    structure = f"; {nc} contour{'s' if nc != 1 else ''}, {busy}" if st else ""
```

and change the final return to include it:

```python
    return (f"{shape}, about {int(round(coverage * 100))}% bright, toward {where}{colour}"
            f"{structure}; {w}×{h} glyph grid, phash {sight.get('phash')}")
```

- [ ] **Step 4: Run the sight tests**

Run: `python -m pytest tests/test_sight.py -v`
Expected: PASS (all -- new + pre-existing). The pre-existing `test_describe_sight_reads_the_glyph_grid_honestly` still passes (it asserts `%`, `phash`, and a shape word -- all still present).

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/sight.py tests/test_sight.py
git commit -m "feat(world): compose structure into the witnessed sight + honest reading"
```

---

## Task 4: Spectator parity -- the same frame, proven

**Files:**
- Test: `tests/test_world_session.py` (or `tests/test_world_server.py` -- whichever already builds a session snapshot; check which exposes `snapshot()`/`sights`)

**Interfaces:**
- Consumes: the world session's `snapshot()` (returns `{... "sights": [...]}`, per `world/server.py:110`).
- Produces: no code -- a test asserting the spectator-facing snapshot carries the byte-identical structure/colour the model read.

- [ ] **Step 1: Inspect how a session/snapshot is built in the existing world tests**

Run: `grep -nE "snapshot|sights|upload|sight_of|World\(|Session" tests/test_world_session.py tests/test_world_server.py`
Expected: find the existing helper that adds an image and reads `snapshot()["sights"]`. Reuse its setup verbatim in Step 2 (do not invent a new harness).

- [ ] **Step 2: Write the failing parity test**

Add to the file that already exercises snapshots (mirror its existing fixture for adding an image). Template (adapt the session setup to match the file's existing pattern):

```python
def test_spectator_sees_the_same_structure_and_colour_the_model_reads():
    # build a session with one witnessed image using this file's existing helper,
    # then assert the snapshot the browser receives carries the SAME channels.
    sight = sight_of_used_by_session  # the sight object the model read (from the helper)
    snap_sight = snapshot["sights"][0]
    assert snap_sight["structure"]["ghash"] == sight["structure"]["ghash"]
    assert snap_sight["structure"]["coords"] == sight["structure"]["coords"]
    assert snap_sight["color"] == sight["color"]
    assert snap_sight["digest"] == sight["digest"]   # one frame, not two
```

If the existing tests construct the sight via `sight_of(path)`, assert parity between `sight_of(path)` and the corresponding entry in `snapshot()["sights"]`.

- [ ] **Step 3: Run to verify it fails (if it fails) or passes**

Run: `python -m pytest tests/ -k "spectator_sees_the_same" -v`
Expected: PASS once Tasks 1--3 are merged (the snapshot serializes the same sight object). If it FAILS because the snapshot strips keys, fix the serialization in `world/server.py`/`world/session.py` so the full sight (including `structure`) reaches the snapshot, then re-run. (No stripping is expected -- snapshots currently pass the sight dict through -- but verify.)

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(world): spectator snapshot carries the same structure+colour the model reads"
```

---

## Task 5: `web/overlay.js` -- pure coord mapping + node test

**Files:**
- Create: `web/overlay.js`
- Create: `web/overlay.test.mjs`

**Interfaces:**
- Produces (ES exports): `normToCanvas(coords, w, h) -> number[][][]` (maps normalized polylines → pixel-space polylines for a `w×h` canvas); `drawContours(ctx, coords, w, h, opts?)`; `LETTER_CSS` (legend-letter → css colour); `renderColorMap(container, color)`. Also attaches `normToCanvas`/`drawContours`/`renderColorMap` to `window` when present, so the classic `together.js` can call them.

- [ ] **Step 1: Write the failing node test**

Create `web/overlay.test.mjs`:

```javascript
// Node gate for the browser contour overlay: normalized [0,1] coords must map to
// canvas pixels exactly, so what the spectator sees overlays the same frame.
// Run: node --test web/overlay.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { normToCanvas } from "./overlay.js";

test("normToCanvas scales normalized polylines to canvas pixels", () => {
  const out = normToCanvas([[[0, 0], [1, 1], [0.5, 0.5]]], 200, 100);
  assert.deepEqual(out, [[[0, 0], [200, 100], [100, 50]]]);
});

test("normToCanvas handles multiple paths and empty input", () => {
  assert.deepEqual(normToCanvas([], 10, 10), []);
  assert.deepEqual(normToCanvas([[[0.25, 0.5]]], 40, 20), [[[10, 10]]]);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test web/overlay.test.mjs`
Expected: FAIL -- cannot resolve `./overlay.js`.

- [ ] **Step 3: Write `overlay.js`**

```javascript
// overlay.js -- draw the witnessed structure + colour on the spectator's canvas.
//
// The model reads sight.structure.coords (polylines normalized to [0,1]) and
// sight.color.map (legend letters). Here the spectator sees the SAME data drawn
// over the same photo -- one frame, two ways of seeing. Pure coord math is
// exported for a node test; the browser also gets these on `window`.

// Map normalized [0,1] polylines to pixel coords for a w×h canvas. Pure.
export function normToCanvas(coords, w, h) {
  return coords.map(path => path.map(([x, y]) => [x * w, y * h]));
}

// Stroke the witnessed contours on a 2D context sized w×h.
export function drawContours(ctx, coords, w, h, opts = {}) {
  const paths = normToCanvas(coords, w, h);
  ctx.clearRect(0, 0, w, h);
  ctx.lineWidth = opts.lineWidth || 1.5;
  ctx.strokeStyle = opts.stroke || "rgba(255,80,0,0.9)";
  ctx.lineJoin = "round";
  for (const path of paths) {
    if (path.length < 2) continue;
    ctx.beginPath();
    ctx.moveTo(path[0][0], path[0][1]);
    for (let i = 1; i < path.length; i++) ctx.lineTo(path[i][0], path[i][1]);
    ctx.stroke();
  }
}

// Legend letter -> a representative css colour (mirrors sight.py _LEGEND).
export const LETTER_CSS = {
  k: "#111", w: "#eee", n: "#888", r: "#d23", o: "#e72",
  y: "#dd3", g: "#2b6", c: "#2bd", b: "#36d", m: "#a3c",
};

// Render the spatial colour map (rows of legend letters) into a container as a grid of swatches.
export function renderColorMap(container, color) {
  if (!container) return;
  const map = (color && color.map) || [];
  container.style.display = "grid";
  container.style.gridTemplateColumns = `repeat(${(map[0] || "").length || 1}, 1fr)`;
  container.innerHTML = map.flatMap(row =>
    [...row].map(ch => `<span style="background:${LETTER_CSS[ch] || "#000"}" title="${ch}"></span>`)
  ).join("");
}

if (typeof window !== "undefined") {
  window.normToCanvas = normToCanvas;
  window.drawContours = drawContours;
  window.renderColorMap = renderColorMap;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `node --test web/overlay.test.mjs`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add web/overlay.js web/overlay.test.mjs
git commit -m "feat(web): pure contour-overlay coord mapping + colour-map renderer (node-tested)"
```

---

## Task 6: Draw the contours + colour map in `together`

**Files:**
- Modify: `web/together.html` (add overlay canvas, colour-map panel, module script)
- Modify: `web/together.js` (call `drawContours` + `renderColorMap` in `showOverlay`)

**Interfaces:**
- Consumes: `window.drawContours`, `window.renderColorMap` (Task 5); `sight.structure.coords`, `sight.color` (Tasks 1--3).
- Produces: visible contour overlay on the photo + a colour-map panel in the bilateral view.

- [ ] **Step 1: Add the overlay canvas, colour panel, and module script to `together.html`**

Inside `<div class="viewer" id="viewer">` (around line 97), add an overlay canvas as a sibling of the photo (it must sit above `<img id="photo">` in z-order -- give it `position:absolute; inset:0; pointer-events:none`):

```html
        <canvas id="overlay" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></canvas>
```

After the `<div class="sight-meta" id="sight-meta"></div>` (line 107), add the colour-map panel:

```html
      <div class="color-map" id="color-map" aria-label="the witnessed colour map"></div>
```

Before the existing `together.js` script tag, load the overlay module:

```html
    <script type="module" src="overlay.js"></script>
```

- [ ] **Step 2: Draw in `showOverlay` (`together.js`)**

In `showOverlay`, extend the `photo.onload` handler (currently lines 57--60) so the overlay canvas is sized to the rendered photo and the contours are drawn, and render the colour map:

```javascript
  const photo = $("photo");
  photo.onload = () => {
    $("viewer").style.aspectRatio = (photo.naturalWidth / photo.naturalHeight) || 1;
    fitAscii(sight);
    const cv = $("overlay");
    if (cv && window.drawContours) {
      cv.width = photo.clientWidth; cv.height = photo.clientHeight;
      const st = sight.structure || {};
      window.drawContours(cv.getContext("2d"), st.coords || [], cv.width, cv.height);
    }
  };
  if (window.renderColorMap) window.renderColorMap($("color-map"), sight.color);
  photo.src = dataUrl;
```

(Keep the rest of `showOverlay` unchanged: the `$("sight-meta")` line, `setWipe`, `chat-empty` removal.)

- [ ] **Step 3: Re-run the frontend node test (regression)**

Run: `node --test web/overlay.test.mjs`
Expected: PASS -- unchanged (Step 2 only wires the already-tested pure functions).

- [ ] **Step 4: Visual confirmation via Playwright (once)**

Start the world server serving `together.html`, navigate, upload `_disc_png`-equivalent, and confirm the overlay canvas has non-blank pixels and `#color-map` has children. Use the playwright MCP tools:
- `browser_navigate` to the local `together.html` URL the world server serves.
- Drive the upload (or `browser_evaluate` to POST `./upload` then call `showOverlay`).
- `browser_evaluate`: assert `document.getElementById("overlay").getContext("2d").getImageData(...)` contains non-zero alpha pixels, and `document.getElementById("color-map").children.length > 0`.
- `browser_take_screenshot` for the record (the bilateral "same frame" -- contours on the photo).

Expected: contours visibly stroked over the photo; colour-map panel populated. This evidences the bilateral claim rather than asserting it.

- [ ] **Step 5: Commit**

```bash
git add web/together.html web/together.js
git commit -m "feat(web): draw the witnessed contours + colour map in the bilateral view"
```

---

## Final verification

- [ ] Run the targeted slice: `python -m pytest tests/test_sight.py tests/test_world_session.py tests/test_world_server.py -v` -- all green.
- [ ] Run the frontend gate: `node --test web/overlay.test.mjs` -- green.
- [ ] Confirm no new third-party imports: `grep -rnE "^import |^from " src/accountable_surface/world/structure.py` shows only stdlib + `coherence_membrane`.
- [ ] The Playwright screenshot from Task 6 Step 4 exists as the evidence artifact.

## Self-Review (completed by plan author)

- **Spec coverage:** structure channel (T1, T3), OKLab colour + merged palette (T2), describe_sight (T3), payload shape incl. normalized coords + ghash (T1), fail-closed empty structure (T1), spectator parity (T4), web overlay + colour map (T5--T6), Playwright visual (T6). All spec sections map to a task.
- **Placeholder scan:** the only non-literal code is Task 4 Step 2, deliberately templated because the exact session fixture must mirror the existing world test (Step 1 inspects it first) -- flagged, not hidden.
- **Type consistency:** `witness_structure(img)` takes a decoded image in T1 and is called with the already-decoded `img` in T3; `normToCanvas`/`drawContours`/`renderColorMap` names match across T5 and T6; palette `oklab` key matches across T2 test and impl.
