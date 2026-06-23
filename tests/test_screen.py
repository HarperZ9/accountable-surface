"""Tests for the live capture witnessing loop — source-agnostic, deterministic.

We never grab the real screen here: a fake CaptureSource (cm's IterableFrameSource)
feeds known PNGs, so the loop's pacing, bounding, and change-proportional skipping
are tested with no wall-clock and no platform dependency.
"""
from __future__ import annotations

import math

from coherence_membrane.pngencode import encode_png
from coherence_membrane.capture import IterableFrameSource

from accountable_surface.grant import action_authorization
from accountable_surface.surface import AccountableSurface
from accountable_surface.world.screen import witness_capture
from accountable_surface.world.server import World, _sandbox_grant
from accountable_surface.world.session import screen_capture_allowed


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


def test_start_capture_refused_when_already_capturing(tmp_path):
    world = _granted_world(tmp_path)
    world._screen_source = lambda region: IterableFrameSource([_disc_png()])  # backend present
    world._capturing = True                                                   # already running
    res = world.start_capture()
    assert "already running" in res["error"]


def test_start_capture_refused_when_no_backend(tmp_path):
    world = _granted_world(tmp_path)
    world._screen_source = lambda region: None                                # simulate no backend
    res = world.start_capture(region=[0, 0, 10, 10])
    assert "backend" in res["error"]


def test_stop_capture_clears_the_flag(tmp_path):
    world = _granted_world(tmp_path)
    world._capturing = True
    world.stop_capture()
    assert world._capturing is False


def test_start_capture_returns_witnessed_refusal_dict_without_grant(tmp_path):
    # The endpoint maps start_capture's refusal to a clean error response; we test the
    # decision at the World level (the routing is a thin pass-through over this).
    world = World(tmp_path, _sandbox_grant())
    res = world.start_capture(region=[0, 0, 10, 10])
    assert res.get("error") and "screen" in res["error"]
    # stop is always safe / idempotent
    world.stop_capture()
    assert world._capturing is False


def test_granted_perception_does_not_break_actions(tmp_path):
    g = _sandbox_grant()
    g["scope"]["allowed_perceptions"] = ["screen"]
    w = World(tmp_path / "w", g)
    step = w.act(kind="fs.write", target="y.txt", content="yo")
    assert step["decision"] == "allow" and step["acted"]
    assert "y.txt" in [f["name"] for f in w.snapshot()["files"]]


# --- Regression: action_authorization strips allowed_perceptions at MCP boundary ---

def _grant_with_perceptions(actions=("summarize",), targets=()):
    """A grant that carries allowed_perceptions — the shape operators use for screen access."""
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-reg-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "reg-agent"},
        "intent": "regression test — allowed_perceptions must not reach proof-surface schema",
        "scope": {
            "allowed_actions": list(actions),
            "allowed_targets": list(targets),
            "allowed_perceptions": ["screen"],
        },
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def test_action_authorization_strips_allowed_perceptions():
    """action_authorization removes allowed_perceptions so proof-surface sees a clean scope."""
    grant = _grant_with_perceptions()
    stripped = action_authorization(grant)
    assert "allowed_perceptions" not in stripped["scope"]
    assert stripped["scope"]["allowed_actions"] == ["summarize"]
    # original must be untouched
    assert "allowed_perceptions" in grant["scope"]


def test_action_authorization_is_noop_when_no_perceptions():
    """action_authorization returns the original when there's nothing to strip."""
    grant = {
        "scope": {"allowed_actions": ["summarize"]},
    }
    assert action_authorization(grant) is grant


def test_action_authorization_is_noop_on_non_dict():
    """action_authorization is total: non-dict passes through unchanged."""
    assert action_authorization(None) is None
    assert action_authorization("raw") == "raw"


def test_mcp_propose_with_allowed_perceptions_not_schema_rejected():
    """A grant carrying allowed_perceptions must NOT be rejected by proof-surface's
    closed schema when routed through the MCP propose path. The decision should be
    allow (for an authorised action) — NOT a deny caused by an unexpected scope field."""
    from accountable_surface.server import propose_impl

    grant = _grant_with_perceptions(actions=["summarize"])
    surface = AccountableSurface()
    # propose_impl applies action_authorization internally; result must be allow, not an
    # authorization-schema-triggered deny.
    out = propose_impl(surface, [grant], "summarize", "page")
    assert out["decision"] == "allow", (
        f"Expected allow but got {out['decision']!r}; reasons: {out.get('reasons')}"
    )
    assert out["executed"] is False
