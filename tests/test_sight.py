"""Tests for witnessed sight — what the model actually sees when it looks at visual material.

An image becomes a faithful, re-derivable ASCII glyph grid (the model reads it natively and a
spectator sees the SAME grid) plus a perceptual hash and a content digest. Composes
coherence-membrane's image organs; stdlib only. We build test images with cm's own PNG encoder.
"""
from __future__ import annotations

from coherence_membrane.pngencode import encode_png

from accountable_surface.world.sight import witness_image, sight_of, describe_sight


def _gradient_png(w=16, h=8):
    px = bytearray()
    for _y in range(h):
        for x in range(w):
            v = int(255 * x / (w - 1))
            px += bytes([v, v, v])
    return encode_png(w, h, bytes(px), channels=3)


def test_witness_image_is_a_glyph_grid_with_provenance():
    sight = witness_image(_gradient_png(), cols=16)
    assert sight["kind"] == "image"
    assert sight["width"] == 16 and sight["height"] == 8
    assert isinstance(sight["ascii"], list) and len(sight["ascii"]) >= 1
    assert all(len(row) == 16 for row in sight["ascii"])  # cols honored
    assert sight["digest"].startswith("sha256:")
    assert len(sight["phash"]) == 16  # 64-bit dHash as hex


def test_witnessed_sight_is_re_derivable_and_renders_the_image():
    png = _gradient_png()
    assert witness_image(png)["digest"] == witness_image(png)["digest"]  # deterministic
    grid = witness_image(png, cols=16)["ascii"]
    assert grid[0][0] == " " and grid[0][-1] in "%@#"  # left dark, right bright — a real perception


def test_sight_of_an_image_file(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(_gradient_png())
    sight = sight_of(p)
    assert sight is not None
    assert sight["name"] == "img.png" and sight["kind"] == "image"


def test_sight_of_a_non_image_is_none(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("not an image", encoding="utf-8")
    assert sight_of(p) is None  # can't see it as an image != lying about it


def _disc_png(w=40, h=40):
    import math
    px = bytearray()
    cx, cy, r = w / 2, h / 2, min(w, h) * 0.35
    for y in range(h):
        for x in range(w):
            v = 235 if math.hypot(x - cx, y - cy) < r else 22
            px += bytes([v, v, v])
    return encode_png(w, h, bytes(px), channels=3)


def _split_png(top, bottom, w=24, h=24):
    px = bytearray()
    for y in range(h):
        rgb = top if y < h // 2 else bottom
        for _x in range(w):
            px += bytes(rgb)
    return encode_png(w, h, bytes(px), channels=3)


def test_witnessed_sight_includes_colour_palette_and_spatial_map():
    s = witness_image(_split_png((220, 40, 40), (40, 180, 70)), cols=24)  # red over green
    assert "color" in s
    names = " ".join(p["name"] for p in s["color"]["palette"])
    assert "red" in names and "green" in names              # it perceives the actual colours
    grid = s["color"]["map"]
    assert "r" in grid[0] and "g" in grid[-1]               # and WHERE they sit (top red, bottom green)
    assert s["color"]["legend"].get("r") == "red" and s["color"]["legend"].get("g") == "green"


def test_describe_sight_reads_the_glyph_grid_honestly():
    sight = witness_image(_disc_png(), cols=32)
    desc = describe_sight(sight)
    assert isinstance(desc, str) and desc
    assert "%" in desc                 # an honest coverage estimate
    assert sight["phash"] in desc      # cites the witnessed phash (re-checkable)
    assert any(w in desc.lower() for w in ("bright", "region", "field"))  # says what it sees


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
    assert st["contours"] == 0                        # no edges — and we say so
    assert st["outline"] == "no distinct edges"
    assert st["coords"] == []
    assert len(st["ghash"]) == 16                     # key present, never omitted


def test_structure_ghash_is_deterministic():
    a = witness_structure(decode_png(_disc_png()))
    b = witness_structure(decode_png(_disc_png()))
    assert a["ghash"] == b["ghash"] and a["coords"] == b["coords"]
