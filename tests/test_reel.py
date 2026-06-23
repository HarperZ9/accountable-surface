"""Tests for the reel — moving material as a sequence of witnessed ASCII frames.

A directory of image frames becomes a playable reel: each frame the same shared sight the model
and a spectator both watch, in order. Composes the witnessed sight; stdlib only. We build frames
with coherence-membrane's PNG encoder.
"""
from __future__ import annotations

from coherence_membrane.pngencode import encode_png

from accountable_surface.world.reel import load_reel


def _frame(shade, w=8, h=8):
    return encode_png(w, h, bytes([shade] * w * h * 3), channels=3)


def test_load_reel_builds_witnessed_frames_in_order(tmp_path):
    d = tmp_path / "reel"
    d.mkdir()
    for i, sh in enumerate([20, 120, 220]):
        (d / f"frame-{i:03d}.png").write_bytes(_frame(sh))
    reel = load_reel(d, cols=8, fps=10)
    assert reel["count"] == 3 and reel["fps"] == 10
    assert [f["name"] for f in reel["frames"]] == ["frame-000.png", "frame-001.png", "frame-002.png"]
    assert all("ascii" in f and "phash" in f and "digest" in f for f in reel["frames"])


def test_load_reel_is_none_when_empty_or_missing(tmp_path):
    assert load_reel(tmp_path / "does-not-exist") is None
    (tmp_path / "empty").mkdir()
    assert load_reel(tmp_path / "empty") is None
