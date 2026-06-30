# Bilateral Eye -- Increment 1 Design

*2026-06-22 · branch `feat/bilateral-renderer` · MIT*

## Telos (why this exists)

The complete engine is an **engine-agnostic, material-agnostic accountable workspace
layer**: an AI works on the PC on any material, every move gated and witnessed, while the
human sees and verifies the *same frame* at the same time. The **bilateral renderer is the
eye** of that engine; `ScreenCaptureSource` (a later increment) makes the eye
material-agnostic; the accountable surface is the hand.

This increment builds the eye's first full composition: a witnessed sight that carries
**shape + structure + OKLab color**, and a spectator view that draws the *same* structure
and color the model reads -- so what the AI perceives and what the human verifies are
provably one frame.

The eye is **domain-neutral**: the same witnessed surface serves whatever launches from
it -- perception, creativity, invention, security alike -- not security alone. Accountability
is the runway, not a guardrail bolted onto a security tool (superproject VISION
§"Accountability as the runway -- a launch surface, not only a guardrail").

Scope decision (confirmed): **data layer + web overlay together** -- the bilateral "same
frame" lands in one increment, not split.

## Non-goals

- No screen capture yet (Increment 2 -- `ScreenCaptureSource`).
- No GPU-native rendering (Increment 3 -- RAW).
- No semantic understanding of the image; only re-derivable, honest perception.
- No new third-party dependencies. coherence-membrane stays stdlib-only.

## Architecture & boundaries

Three touch points; the organ-composition boundary is preserved (`sight.py` composes cm
organ APIs, never reaches into raw pixels except through them).

| Unit | Change | Purpose |
|------|--------|---------|
| `src/accountable_surface/world/sight.py` | upgrade | The eye. Adds the `structure` channel; replaces hand-rolled HSV color with OKLab-grounded color. Single place image bytes → witnessed sight. |
| `src/accountable_surface/world/structure.py` | **new (small)** | The image→contour lowering, kept out of `sight.py` so each file stays focused. Pure, deterministic. |
| `web/together.js` + `web/together.html` | upgrade | Draws simplified contours on the existing image canvas; renders the OKLab map. Spectator sees the actual traced edges on the actual photo. |

### `structure.py` -- the lowering

```
decode_png(payload)
  → luminance Field (per-pixel luma, FieldKind.LUMINANCE)
  → field_ops.downscale(field, ~128 wide, aspect-preserved)   # keep pure-Python contour cheap
  → geometry_ops.contour(field, level=0.5)                     # Geometry of edge polylines
  → geometry_ops.stitch(geometry)                              # join open ends
  → geometry_ops.simplify_geometry(geometry, epsilon)          # Douglas--Peucker, fewer points
  → normalize coords to [0,1] (divide by field w/h)
  → return {contours, edge_ink, outline, coords, ghash}
```

- **contours**: number of polylines after stitch+simplify.
- **edge_ink**: total contour length / frame diagonal-normalized measure → "sparse" vs "busy".
- **outline**: a legible reading derived from the geometry bbox + centroid (e.g.
  "a single closed form, centred"). Coarse and honest; not semantics.
- **coords**: list of polylines, each a list of `[x, y]` floats **normalized to [0,1]**, so
  the frontend scales to any canvas without knowing field resolution.
- **ghash**: `sha256` of the rounded coords (fixed decimals) -- structure is independently
  re-checkable, not merely folded into the image digest.

### Color (OKLab) in `sight.py`

- Build OKLab per cell: `color.srgb_to_oklab(rgb)` (or via `color_field.color_field_from_png`
  then `downscale_color_field` for the spatial map).
- Classify each cell to one of the **same 10 legend letters** (dark/light/grey + 7 hues) by
  **nearest fixed OKLab anchor** via `color.delta_e_ok` -- perceptually-correct boundaries
  replacing hand-tuned HSV cutoffs. Legend stays stable (existing tests/legend hold).
- Palette: build "dominant colours" by **`delta_e`-merging perceptually-near cells** so
  near-identical shades count once; each palette entry carries its mean OKLab triple and pct.

## Witnessed-sight payload

`witness_image()` returns existing keys plus one new block. Everything re-derivable from the
same `payload`; the `digest` still covers it all.

```
{
  kind, width, height,
  ascii:  [...],                      # SHAPE -- unchanged (ascii_view)
  color:  {map, palette, legend},     # COLOR -- OKLab-grounded; palette entries carry OKLab
  structure: {                        # STRUCTURE -- new
     contours: 3,
     edge_ink: 0.18,
     outline: "a single closed form, centred",
     coords: [[[x,y],...], ...],      # simplified polylines, normalized to [0,1]
     ghash: "9f3c..."
  },
  phash, digest
}
```

## Error handling (fail-closed)

- Header-bomb guard unchanged: refuse > 4 MP before decode.
- Contour failure or no edges (flat image): `structure = {contours: 0, edge_ink: 0.0,
  outline: "no distinct edges", coords: [], ghash: <hash of []>}`. We say "no edges"; we
  never omit the key or fabricate lines. "Can't see structure" ≠ lying -- same ethos as
  `sight_of` returning `None` for a non-image.
- OKLab is total over valid RGB; ColorField's `unknown` mask marks UNVERIFIABLE cells rather
  than guessing.

## `describe_sight` + offline reading

Extend the honest reading to cite structure:
> "…a compact bright region, ~31% bright, toward the centre; 3 contours, clean edges;
> colours: red 41%, green 33%; 32×16 glyph grid, phash …"

Still anchored to `phash`, still re-derivable, no semantics invented. `_offline_reply` in
`world/server.py` inherits the richer reading for free.

## Spectator rendering (`together.js` / `together.html`)

- `showOverlay(dataUrl, sight)` already draws the original image on a canvas beside the ASCII
  grid ("the same frame, two ways of seeing"). Add:
  1. **Contour overlay** -- map `sight.structure.coords` (normalized) → canvas pixels and
     stroke the polylines over the image.
  2. **OKLab map panel** -- render `sight.color.map` legend grid with the legend.
- Coord mapping extracted into a **pure function** (`normToCanvas(coords, w, h)`) so it's
  unit-testable without a browser.

## Testing (TDD -- tests first)

Targeted slice only (per testing-strategy rule): `tests/test_sight.py` + world-server tests,
plus the frontend node test. No full-suite run unless requested.

- **Python (`tests/test_sight.py`)**
  - disc PNG → `structure.contours >= 1`, outline reads "centred".
  - flat PNG → `structure.contours == 0` honestly; key present.
  - `ghash` deterministic across two runs; all coords within [0,1].
  - OKLab split-PNG → palette still yields red + green (existing test stays green).
  - palette merge collapses two near-identical reds into one entry.
  - `describe_sight` cites contour count and still cites `phash`.
- **Spectator parity** -- the snapshot the browser receives carries the identical
  `structure`/`color` the model read (same `digest`/`ghash`): proves "the same frame."
- **Frontend (`web/` node test, sibling of `recheck.test.mjs`)** -- `normToCanvas` maps
  normalized coords → canvas pixels correctly.
- **Visual confirmation (once)** -- Playwright against a running `together.html`: contours
  visibly drawn on the photo + OKLab map present. Evidences the bilateral claim, not asserts.

## Increment ladder (context)

- **Inc 1 (this):** sight.py + structure.py + describe_sight + OKLab + web overlay + parity test.
- **Inc 2:** `ScreenCaptureSource` -- perceive any material on screen (engine-agnostic eye).
- **Inc 3:** RAW -- GPU-native rendering depths.
