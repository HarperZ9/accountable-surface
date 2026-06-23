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


from accountable_surface.world.session import screen_capture_allowed
from accountable_surface.world.server import World, _sandbox_grant
from coherence_membrane.capture import IterableFrameSource


def test_screen_capture_default_deny():
    assert screen_capture_allowed({"scope": {"allowed_perceptions": []}}) is False
    assert screen_capture_allowed({"scope": {}}) is False
    assert screen_capture_allowed({}) is False
    assert screen_capture_allowed(None) is False


def test_screen_capture_allowed_when_granted():
    assert screen_capture_allowed({"scope": {"allowed_perceptions": ["screen"]}}) is True


def test_sandbox_grant_defaults_to_no_perceptions():
    assert _sandbox_grant()["scope"]["allowed_perceptions"] == []


def _granted_world(tmp_path):
    grant = _sandbox_grant()
    grant["scope"]["allowed_perceptions"] = ["screen"]
    return World(tmp_path, grant)


def _drain(world):
    q = world.subscribe()
    events = []
    try:
        while True:
            events.append(q.get_nowait())
    except Exception:
        pass
    finally:
        world.unsubscribe(q)
    return events


def test_start_capture_refused_without_grant(tmp_path):
    world = World(tmp_path, _sandbox_grant())          # default: no 'screen'
    res = world.start_capture()
    assert "error" in res and "screen" in res["error"]


def test_run_capture_streams_witnessed_frames(tmp_path):
    world = _granted_world(tmp_path)
    world._screen_source = lambda region: IterableFrameSource([_disc_png(), _disc_png(120)])
    q = world.subscribe()
    world.run_capture(None, max_frames=10, interval=0.0)   # synchronous: run the thread body directly
    events = []
    try:
        while True:
            events.append(q.get_nowait())
    except Exception:
        pass
    finally:
        world.unsubscribe(q)
    caps = [d for (k, d) in events if k == "capture" and "sight" in d]
    assert len(caps) == 2
    assert "structure" in caps[0]["sight"] and "color" in caps[0]["sight"]
    assert any(k == "capture" and "receipt" in d for (k, d) in events)   # stop receipt emitted


def test_run_capture_refused_when_backend_unavailable(tmp_path):
    world = _granted_world(tmp_path)
    world._screen_source = lambda region: None         # simulate capture_available() False
    q = world.subscribe()
    world.run_capture(None, max_frames=10, interval=0.0)
    events = []
    try:
        while True:
            events.append(q.get_nowait())
    except Exception:
        pass
    finally:
        world.unsubscribe(q)
    assert any(k == "capture" and "error" in d for (k, d) in events)
