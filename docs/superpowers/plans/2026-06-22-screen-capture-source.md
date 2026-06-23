# Screen Capture Source — Increment 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bilateral eye engine-agnostic — perceive whatever is on screen as a live, consent-gated, bounded, witnessed source, streaming the witnessed sight to the spectator the same way increment 1 did for uploads.

**Architecture:** A small source-agnostic witnessing loop (`world/screen.py`) pulls frames from any coherence-membrane `CaptureSource`, witnesses each via `witness_image` (the increment-1 eye), and is bounded/change-proportional. The `World` orchestrates capture exactly like autopilot (gated, atomic, daemon thread, SSE), behind two locks (a granted `allowed_perceptions` capability + an explicit start). The spectator view renders the live witnessed sight reusing the shipped `overlay.js`.

**Tech Stack:** Python 3 (stdlib + `coherence_membrane` only; capture is cm's native ctypes grab). Vanilla ES-module JS. `pytest`, `node --test`, one controller Playwright live check.

## Global Constraints

- **Zero third-party deps.** Python imports only stdlib + `coherence_membrane`. Frontend vanilla JS.
- **Default-deny, fail-closed.** `allowed_perceptions` defaults `[]`; no grant OR no backend (`capture_available()` False) → witnessed refusal, capture nothing, never crash.
- **Two locks.** Capture runs only when granted (`"screen" in allowed_perceptions`) AND explicitly started.
- **Witnessed + bounded + stoppable.** Region recorded; per-frame phash+digest ride in each sight; `max_frames` + `interval` cap cost; change-proportional (skip a frame whose phash == previous); stoppable.
- **No raw-pixel streaming.** The shared medium is the witnessed sight (the increment-1 sight object), not screen pixels.
- **Source-agnostic core.** `screen.py` never imports a graphics API; it takes a `CaptureSource`. Production passes `ScreenCaptureSource`; tests inject `IterableFrameSource` (no real grab in tests).
- **Files focused, <300 lines; functions <50 lines.** TDD. Targeted test slice only.

### Signatures this plan consumes (verbatim)

- `coherence_membrane.native_capture.ScreenCaptureSource(region=None, source_id="screen")` → `.frames()` yields `Frame`; `capture_available() -> bool`. region = `(x,y,w,h)` or `None`.
- `coherence_membrane.capture.CaptureSource` (Protocol: `frames() -> Iterator[Frame]`); `Frame.read() -> bytes`; `IterableFrameSource(items, *, source_id=..., pixel_format=...)` (items = list of `bytes`).
- `accountable_surface.world.sight.witness_image(payload, *, cols=96) -> dict` with keys `ascii, color, structure, phash, digest, width, height, kind`.
- `World` (in `world/server.py`): `self._lock`, `self._subs` (list of `queue.Queue`), `self.session` (`WorldSession`), `self.session.grant`, `subscribe()/unsubscribe()`; SSE pushes are `q.put((event_name, data_dict))`; the autopilot pattern (`run_autopilot`/`stop_autopilot`, atomic check-and-set, daemon thread) is the model to mirror.
- `WorldSession.grant` is the grant dict; `grant["scope"]["allowed_actions"]` exists; we add `grant["scope"]["allowed_perceptions"]`.
- `do_POST` routes by `path`; `_send(code, body)`; existing tests build a world via `World(root, _sandbox_grant())`.

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `src/accountable_surface/world/screen.py` | Create | `witness_capture(...)` — source-agnostic, deterministic witnessing loop (bounded, change-proportional, injectable `sleep`/`should_stop`); returns a receipt dict. |
| `src/accountable_surface/world/session.py` | Modify | `screen_capture_allowed(grant) -> bool` (default-deny). |
| `src/accountable_surface/world/server.py` | Modify | `World.start_capture/run_capture/stop_capture` + `World._screen_source` seam; `_sandbox_grant` gains `allowed_perceptions`; POST `/capture/start` + `/capture/stop`. |
| `web/screen.html` + `web/screen.js` | Create | Live spectator view rendering the witnessed sight per `("capture", …)` SSE event (reuses `overlay.js`). |
| `tests/test_screen.py` | Create | Unit tests for the loop + the World capture orchestration + the gate (injected fake source; no real grab). |

---

## Task 1: `screen.py` — the witnessing loop

**Files:**
- Create: `src/accountable_surface/world/screen.py`
- Test: `tests/test_screen.py`

**Interfaces:**
- Consumes: `witness_image` (inc 1); a `CaptureSource` (cm `capture.py` Protocol); `Frame.read()`.
- Produces: `witness_capture(source, *, max_frames=120, interval=1.0, cols=96, sleep=time.sleep, should_stop=lambda: False, on_frame) -> dict`. Calls `on_frame(frame_index: int, sight: dict)` per *emitted* (changed) frame; returns a receipt `{"frames": <emitted count>, "stopped": <bool>}`. Change-proportional: a frame whose `sight["phash"]` equals the previous emitted phash is skipped (not emitted). Stops when `should_stop()` is True, `max_frames` emitted, or the source is exhausted.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screen.py`:

```python
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


def test_witness_capture_is_change_proportional():
    a = _disc_png()
    src = IterableFrameSource([a, a, a])           # three IDENTICAL frames
    seen, rcpt = _collect(src)
    assert rcpt["frames"] == 1 and len(seen) == 1  # duplicates skipped by phash


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: accountable_surface.world.screen`.

- [ ] **Step 3: Write `screen.py`**

```python
"""The live capture witnessing loop — the engine-agnostic eye, moving.

Pulls frames from any coherence-membrane CaptureSource (a screen grabber in
production, a fake in tests), witnesses each via the increment-1 eye
(witness_image: shape + structure + OKLab colour + provenance), and hands each
*changed* frame to a callback. Source-agnostic by construction (never imports a
graphics API), deterministic (sleep + should_stop are injected), bounded, and
change-proportional (an unchanged frame — same perceptual hash — is skipped, not
re-witnessed downstream). Stdlib + coherence-membrane only.
"""
from __future__ import annotations

import time
from typing import Callable

from .sight import witness_image


def witness_capture(
    source,
    *,
    on_frame: Callable[[int, dict], None],
    max_frames: int = 120,
    interval: float = 1.0,
    cols: int = 96,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
) -> dict:
    """Witness frames from `source` until stopped, bounded, or exhausted.

    Calls on_frame(frame_index, sight) per CHANGED frame (phash != previous).
    Returns a receipt {"frames": emitted, "stopped": bool}. A frame that can't be
    witnessed (undecodable grab) is skipped, never faked.
    """
    emitted = 0
    last_phash = None
    stopped = False
    for frame in source.frames():
        if should_stop():
            stopped = True
            break
        if emitted >= max_frames:
            break
        try:
            sight = witness_image(frame.read(), cols=cols)
        except Exception:
            continue  # an undecodable grab: we honestly can't see it, we don't pretend to
        if sight["phash"] == last_phash:
            sleep(interval)
            continue  # change-proportional: nothing new to witness
        last_phash = sight["phash"]
        on_frame(frame.descriptor.frame_index, sight)
        emitted += 1
        sleep(interval)
    return {"frames": emitted, "stopped": stopped}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_screen.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/screen.py tests/test_screen.py
git commit -m "feat(world): the live capture witnessing loop (source-agnostic, change-proportional)"
```

---

## Task 2: the perception gate + grant

**Files:**
- Modify: `src/accountable_surface/world/session.py` (add `screen_capture_allowed`)
- Modify: `src/accountable_surface/world/server.py` (`_sandbox_grant` gains `allowed_perceptions`)
- Test: `tests/test_screen.py`

**Interfaces:**
- Produces: `accountable_surface.world.session.screen_capture_allowed(grant) -> bool` — True iff `"screen"` is in `grant["scope"]["allowed_perceptions"]`. Total over a missing/None grant or missing keys (→ False).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_screen.py`:

```python
from accountable_surface.world.session import screen_capture_allowed


def test_screen_capture_default_deny():
    assert screen_capture_allowed({"scope": {"allowed_perceptions": []}}) is False
    assert screen_capture_allowed({"scope": {}}) is False
    assert screen_capture_allowed({}) is False
    assert screen_capture_allowed(None) is False


def test_screen_capture_allowed_when_granted():
    assert screen_capture_allowed({"scope": {"allowed_perceptions": ["screen"]}}) is True


def test_sandbox_grant_defaults_to_no_perceptions():
    from accountable_surface.world.server import _sandbox_grant
    assert _sandbox_grant()["scope"]["allowed_perceptions"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screen.py -k "deny or granted or sandbox_grant" -v`
Expected: FAIL — `ImportError: cannot import name 'screen_capture_allowed'`.

- [ ] **Step 3: Implement the gate + grant field**

In `session.py`, add at module level (after the imports):

```python
def screen_capture_allowed(grant) -> bool:
    """True iff the grant authorizes 'screen' perception. Default-deny, total."""
    scope = (grant or {}).get("scope", {})
    return "screen" in (scope.get("allowed_perceptions") or [])
```

In `server.py`, update `_sandbox_grant` so its `scope` includes the new field (default empty):

```python
            "scope": {"allowed_actions": list(actions), "allowed_targets": [],
                      "allowed_perceptions": []},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_screen.py -k "deny or granted or sandbox_grant" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/session.py src/accountable_surface/world/server.py
git commit -m "feat(world): default-deny screen-perception gate (allowed_perceptions)"
```

---

## Task 3: `World` capture orchestration

**Files:**
- Modify: `src/accountable_surface/world/server.py` (`World`: `_screen_source`, `start_capture`, `run_capture`, `stop_capture`; `__init__` gains `_capturing`)
- Test: `tests/test_screen.py`

**Interfaces:**
- Consumes: `witness_capture` (Task 1), `screen_capture_allowed` (Task 2), cm `ScreenCaptureSource` + `capture_available`.
- Produces:
  - `World._screen_source(region) -> CaptureSource | None` — the real factory: returns `ScreenCaptureSource(region)` if `capture_available()`, else `None`. Tests OVERRIDE this attribute to inject a fake source.
  - `World.start_capture(region=None, max_frames=120, interval=1.0) -> dict` — gate pre-check; returns `{"error": ...}` (witnessed refusal) if not granted / already capturing / no backend, else spawns the daemon thread and returns `{"started": True, "region": <[x,y,w,h] or "full-primary">}`.
  - `World.run_capture(region, max_frames, interval)` — thread body: builds the source, runs `witness_capture` with `on_frame` emitting `("capture", {"frame_index", "sight"})` to subscribers; emits a `("capture", {"receipt": {...}})` stop event; clears `_capturing`.
  - `World.stop_capture()` — sets the stop flag.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_screen.py`:

```python
from accountable_surface.world.server import World, _sandbox_grant
from coherence_membrane.capture import IterableFrameSource


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_screen.py -k "start_capture or run_capture" -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'start_capture'`.

- [ ] **Step 3: Implement the orchestration**

In `server.py`, add the cm imports near the top with the other cm import:

```python
from coherence_membrane.native_capture import ScreenCaptureSource, capture_available
```

and add `from .screen import witness_capture` and `from .session import WorldSession, screen_capture_allowed` (extend the existing `.session` import).

In `World.__init__`, add the capture flag beside `_running`:

```python
        self._capturing = False
```

Add these methods to `World` (mirroring the autopilot pattern):

```python
    def _screen_source(self, region):
        """The real capture source, or None if no native backend is available here.
        Tests override this attribute to inject a fake CaptureSource (no real grab)."""
        if not capture_available():
            return None
        return ScreenCaptureSource(region)

    def _emit(self, event, data):
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            q.put((event, data))

    def start_capture(self, region=None, max_frames=120, interval=1.0) -> dict:
        """Gate, then start a bounded witnessed capture in a daemon thread (mirrors autopilot).
        Two locks: the grant must allow 'screen' AND no capture may already be running."""
        if not screen_capture_allowed(self.session.grant):
            return {"error": "perception 'screen' not granted (default-deny)"}
        with self._lock:
            if self._capturing:
                return {"error": "a capture is already running"}
            self._capturing = True
        region_t = tuple(region) if region else None
        threading.Thread(target=self.run_capture, args=(region_t, max_frames, interval),
                         daemon=True).start()
        return {"started": True, "region": list(region_t) if region_t else "full-primary"}

    def run_capture(self, region, max_frames=120, interval=1.0) -> None:
        """Thread body: witness frames from the source and stream each changed sight.
        Fail-closed: re-check the gate; refuse (witnessed) if not granted or no backend."""
        try:
            if not screen_capture_allowed(self.session.grant):
                self._emit("capture", {"error": "perception 'screen' not granted"})
                return
            source = self._screen_source(region)
            if source is None:
                self._emit("capture", {"error": f"no native capture backend for this platform"})
                return
            self._emit("capture", {"started": True,
                                   "region": list(region) if region else "full-primary"})
            receipt = witness_capture(
                source, max_frames=max_frames, interval=interval,
                should_stop=lambda: not self._capturing,
                on_frame=lambda i, sight: self._emit("capture", {"frame_index": i, "sight": sight}),
            )
            receipt["region"] = list(region) if region else "full-primary"
            self._emit("capture", {"receipt": receipt})
        finally:
            with self._lock:
                self._capturing = False

    def stop_capture(self) -> None:
        with self._lock:
            self._capturing = False
```

Note: `run_capture` sets `_capturing` False in `finally`; when called directly in a test (not via `start_capture`), `should_stop` is `not self._capturing` — so the test must set it. In `test_run_capture_streams_witnessed_frames` the world was not started via `start_capture`, so `_capturing` is False and `should_stop()` would be True immediately. **Fix in implementation:** have `run_capture` set `_capturing = True` at entry if not already, so a direct call self-arms:

```python
    def run_capture(self, region, max_frames=120, interval=1.0) -> None:
        with self._lock:
            self._capturing = True
        try:
            ...
```

(Keep the gate/source checks after arming; the `finally` clears it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_screen.py -v`
Expected: PASS (all — Task 1 + 2 + 3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/server.py tests/test_screen.py
git commit -m "feat(world): gated, bounded, witnessed screen-capture orchestration"
```

---

## Task 4: HTTP endpoints `/capture/start` + `/capture/stop`

**Files:**
- Modify: `src/accountable_surface/world/server.py` (`do_POST` routing)
- Test: `tests/test_screen.py`

**Interfaces:**
- Consumes: `World.start_capture`, `World.stop_capture` (Task 3).
- Produces: POST `/capture/start` (`{region?, max_frames?, interval?}`) → `_send(200, start_capture(...))` or `_send(403, {...})` when refused; POST `/capture/stop` → `_send(200, {"running": False})`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_screen.py`:

```python
def test_start_capture_returns_witnessed_refusal_dict_without_grant(tmp_path):
    # The endpoint maps start_capture's refusal to a clean error response; we test the
    # decision at the World level (the routing is a thin pass-through over this).
    world = World(tmp_path, _sandbox_grant())
    res = world.start_capture(region=[0, 0, 10, 10])
    assert res.get("error") and "screen" in res["error"]
    # stop is always safe / idempotent
    world.stop_capture()
    assert world._capturing is False
```

- [ ] **Step 2: Run test to verify it passes the World-level decision, then wire routing**

Run: `python -m pytest tests/test_screen.py -k "witnessed_refusal_dict" -v`
Expected: PASS (Task 3 already provides `start_capture`/`stop_capture`). This task wires the HTTP routes over them.

- [ ] **Step 3: Add the routes to `do_POST`**

In `server.py` `do_POST`, before the final `return self._send(404, ...)`, add:

```python
        if path == "/capture/start":
            region = body.get("region")
            try:
                max_frames = max(1, min(int(body.get("max_frames", 120) or 120), 1000))
                interval = min(max(float(body.get("interval", 1.0) or 1.0), 0.0), 30.0)
            except (ValueError, TypeError):
                return self._send(400, {"error": "max_frames/interval must be numeric"})
            res = _WORLD.start_capture(region=region, max_frames=max_frames, interval=interval)
            return self._send(200 if res.get("started") else 403, res)
        if path == "/capture/stop":
            _WORLD.stop_capture()
            return self._send(200, {"running": False})
```

- [ ] **Step 4: Run the full screen test file**

Run: `python -m pytest tests/test_screen.py -v`
Expected: PASS (all). Then confirm the world server still imports cleanly:
`python -c "import accountable_surface.world.server"` (with PYTHONPATH set) → no error.

- [ ] **Step 5: Commit**

```bash
git add src/accountable_surface/world/server.py tests/test_screen.py
git commit -m "feat(world): /capture/start + /capture/stop endpoints (gated, bounded)"
```

---

## Task 5: live spectator view (`web/screen.html` + `web/screen.js`)

**Files:**
- Create: `web/screen.html`, `web/screen.js`
- Modify: `src/accountable_surface/world/server.py` (`do_GET`: serve `/screen` → `screen.html`)
- Test: reuse `web/overlay.test.mjs` (already green); a one-time controller Playwright live check (NOT done by the implementer — see scope note).

**Interfaces:**
- Consumes: SSE `/world/stream` `("capture", {...})` events (Task 3); shipped `overlay.js` `window.drawContours` + `window.renderColorMap`; sight shape from `witness_image`.

**SCOPE LIMIT for the implementer:** do Steps 1–4 (HTML, JS, the `/screen` route, and confirming the node gate still passes). SKIP the Playwright live check — the controller runs it (it needs a granted live capture session).

- [ ] **Step 1: Add the `/screen` route**

In `server.py` `do_GET`, beside the `/watch` and `/together` routes, add:

```python
        if path == "/screen":
            return self._static("screen.html")
```

- [ ] **Step 2: Create `web/screen.html`**

```html
<!doctype html>
<meta charset="utf-8">
<title>Screen · The Engine-Agnostic Eye</title>
<style>
  body{margin:0;background:#0b0d10;color:#e8e3d8;font-family:ui-monospace,monospace}
  header{padding:.6rem 1rem;border-bottom:1px solid #222;display:flex;gap:.6rem;align-items:center}
  button{font:inherit;background:#1a1f25;color:#e8e3d8;border:1px solid #333;padding:.3rem .7rem;cursor:pointer}
  input{font:inherit;background:#11151a;color:#e8e3d8;border:1px solid #333;width:4rem}
  #stage{display:grid;grid-template-columns:1fr 1fr;gap:1rem;padding:1rem}
  #ascii{white-space:pre;font-size:7px;line-height:7px;margin:0}
  #frame{position:relative}
  #overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
  #color-map{display:grid;gap:0;margin-top:.5rem;height:48px}
  #color-map span{display:block}
  #meta{padding:0 1rem;color:#9aa;font-size:.8rem}
</style>
<header>
  region <input id="x" placeholder="x"><input id="y" placeholder="y">
  <input id="w" placeholder="w"><input id="h" placeholder="h">
  <button id="start">Start</button><button id="stop">Stop</button>
  <span id="status">idle · capture is OFF by default</span>
</header>
<div id="stage">
  <div id="frame"><pre id="ascii" aria-label="the witnessed glyph grid the model sees"></pre>
    <canvas id="overlay"></canvas></div>
  <div><div id="color-map" aria-label="the witnessed colour map"></div></div>
</div>
<div id="meta"></div>
<script type="module" src="overlay.js"></script>
<script type="module" src="./screen.js"></script>
```

- [ ] **Step 3: Create `web/screen.js`**

```javascript
// screen.js — watch the live witnessed screen: the model and you see the same frame.
//
// Per ("capture", {frame_index, sight}) SSE event we render the witnessed sight the
// model reads — ascii shape + structure contours (overlay.js) + OKLab colour map.
// No raw screen pixels cross the wire; the witnessed sight is the shared medium.

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function render(sight) {
  $("ascii").textContent = (sight.ascii || []).join("\n");
  const cv = $("overlay"), pre = $("ascii");
  cv.width = pre.clientWidth || 320; cv.height = pre.clientHeight || 240;
  if (window.drawContours) window.drawContours(cv.getContext("2d"),
    (sight.structure && sight.structure.coords) || [], cv.width, cv.height);
  if (window.renderColorMap) window.renderColorMap($("color-map"), sight.color);
  $("meta").textContent = `${sight.width}×${sight.height} · phash ${sight.phash} · ` +
    `${(sight.structure && sight.structure.contours) || 0} contours · ${sight.digest}`;
}

const es = new EventSource("/world/stream");
es.addEventListener("capture", e => {
  const d = JSON.parse(e.data);
  if (d.error) { $("status").textContent = "refused: " + d.error; return; }
  if (d.started) { $("status").textContent = "capturing · region " + JSON.stringify(d.region); return; }
  if (d.receipt) { $("status").textContent = `stopped · ${d.receipt.frames} frames witnessed`; return; }
  if (d.sight) render(d.sight);
});

function region() {
  const v = id => parseInt($(id).value, 10);
  const r = [v("x"), v("y"), v("w"), v("h")];
  return r.every(n => Number.isFinite(n)) ? r : null;
}
$("start").addEventListener("click", async () => {
  const res = await (await fetch("/capture/start", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ region: region() }) })).json();
  $("status").textContent = res.error ? "refused: " + res.error : "starting…";
});
$("stop").addEventListener("click", () => fetch("/capture/stop", { method: "POST" }));
```

- [ ] **Step 4: Confirm the node gate still passes (regression)**

Run: `node --test web/overlay.test.mjs`
Expected: PASS (2 tests) — unchanged; `screen.js` only consumes the already-tested pure functions.

- [ ] **Step 5: Commit**

```bash
git add web/screen.html web/screen.js src/accountable_surface/world/server.py
git commit -m "feat(web): live spectator view for the witnessed screen capture"
```

---

## Final verification (controller)

- [ ] Targeted slice: `python -m pytest tests/test_screen.py tests/test_world_server.py tests/test_world_session.py -v` — all green.
- [ ] Frontend gate: `node --test web/overlay.test.mjs` — green.
- [ ] No new third-party imports: `grep -rnE "^import |^from " src/accountable_surface/world/screen.py` shows only stdlib + `coherence_membrane` + `.sight`.
- [ ] **Controller Playwright live check** (the one real-grab confirmation): start the world server with a grant that includes `"screen"` (`allowed_perceptions: ["screen"]`), navigate to `/screen`, click Start, confirm `("capture", …)` events arrive and the ascii/contours/colour render live, then Stop and confirm the receipt. Capture the evidence screenshot.

## Self-Review (completed by plan author)

- **Spec coverage:** witnessing loop + change-proportional + bounds (T1); default-deny gate + grant field (T2); gated/atomic/witnessed orchestration + fail-closed backend-unavailable (T3); HTTP endpoints (T4); live spectator view reusing overlay.js + `/screen` route (T5); controller Playwright live check (final). All spec sections mapped.
- **Placeholder scan:** no TBD/TODO; every code step is complete. The only non-implementer step is the final Playwright check, explicitly assigned to the controller (the spec mandates it as a controller action, mirroring increment 1).
- **Type consistency:** `witness_capture(source, *, on_frame, max_frames, interval, cols, sleep, should_stop)` is identical across T1 definition and T3 call; `screen_capture_allowed(grant)` matches T2↔T3; `start_capture/run_capture/stop_capture/_screen_source` names match T3↔T4↔T5; the `("capture", {...})` event shapes (`started`/`sight`/`receipt`/`error`) match T3 emit ↔ T5 render.
- **Known seam called out:** T3 Step 3 explicitly notes `run_capture` must self-arm `_capturing = True` at entry so a direct (non-`start_capture`) call in tests runs — flagged inline, not hidden.
