"""Tests for the live capture witnessing loop — source-agnostic, deterministic.

We never grab the real screen here: a fake CaptureSource (cm's IterableFrameSource)
feeds known PNGs, so the loop's pacing, bounding, and change-proportional skipping
are tested with no wall-clock and no platform dependency.
"""
from __future__ import annotations

import math

from coherence_membrane.pngencode import encode_png
from coherence_membrane.capture import IterableFrameSource

from accountable_surface.world.screen import witness_capture


def _disc_png(shade=235, w=40, h=40):
    cx, cy, r = w / 2, h / 2, min(w, h) * 0.35
    px = bytearray()
    for y in range(h):
        for x in range(w):
            v = shade if math.hypot(x - cx, y - cy) < r else 22
            px += bytes([v, v, v])
    return encode_png(w, h, bytes(px), channels=3)


def _collect(source, **kw):
    seen = []
    rcpt = witness_capture(source, on_frame=lambda i, s: seen.append((i, s)),
                           sleep=lambda _t: None, **kw)
    return seen, rcpt


def test_witness_capture_witnesses_each_frame_with_structure_and_colour():
    src = IterableFrameSource([_disc_png(), _disc_png(120)])  # two DIFFERENT frames
    seen, rcpt = _collect(src)
    assert rcpt["frames"] == 2 and len(seen) == 2
    for _i, sight in seen:
        assert "structure" in sight and "color" in sight and sight["phash"]
        assert sight["digest"]


def test_witness_capture_is_change_proportional():
    a = _disc_png()
    src = IterableFrameSource([a, a, a])           # three IDENTICAL frames
    seen, rcpt = _collect(src)
    assert rcpt["frames"] == 1 and len(seen) == 1  # duplicates skipped by digest (byte-identical)


def test_witness_capture_honours_max_frames():
    src = IterableFrameSource([_disc_png(s) for s in (235, 200, 160, 120, 80)])
    seen, rcpt = _collect(src, max_frames=2)
    assert rcpt["frames"] == 2 and len(seen) == 2


def test_witness_capture_stops_on_should_stop():
    src = IterableFrameSource([_disc_png(s) for s in (235, 200, 160)])
    calls = {"n": 0}
    def stop():
        calls["n"] += 1
        return calls["n"] > 1          # allow one emit, then stop
    seen = []
    rcpt = witness_capture(src, on_frame=lambda i, s: seen.append(i),
                           sleep=lambda _t: None, should_stop=stop)
    assert rcpt["stopped"] is True and len(seen) == 1
    assert seen == [0]
