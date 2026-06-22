"""Tests for witnessed sight — what the model actually sees when it looks at visual material.

An image becomes a faithful, re-derivable ASCII glyph grid (the model reads it natively and a
spectator sees the SAME grid) plus a perceptual hash and a content digest. Composes
coherence-membrane's image organs; stdlib only. We build test images with cm's own PNG encoder.
"""
from __future__ import annotations

from coherence_membrane.pngencode import encode_png

from accountable_surface.world.sight import witness_image, sight_of


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
