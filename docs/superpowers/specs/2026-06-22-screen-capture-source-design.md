# Screen Capture Source -- Increment 2 Design

*2026-06-22 · branch `feat/screen-capture-source` · MIT*

## Telos (why this exists)

Increment 1 gave the tool an **eye**: a witnessed sight (shape + structure + OKLab colour)
that a model reads and a spectator sees as the *same frame*. That eye perceived uploaded
images. Increment 2 makes the eye **engine-agnostic and material-agnostic**: it perceives
whatever is on screen -- a document, a CAD model, a video, an IDE, a game -- regardless of
what drew it, by capturing the composited display the OS already has.

The capture backend already exists (coherence-membrane `ScreenCaptureSource`, native ctypes,
zero-dep, Windows-GDI validated live). This increment **wires it into the accountable-surface
world** as a live, **consent-gated, bounded, witnessed** perception source, and streams the
witnessed sight to the spectator live -- the bilateral eye, now moving and material-agnostic.

Accountability is the weight here, not the capture: reading the screen reads whatever is
there, so capture is treated as seriously as actuation -- default-deny, gated, witnessed.

Scope (confirmed): the **perception half** -- live screen → witnessed sight → spectator
watches live; the model can read the current sight via the existing chat/snapshot path.
Autonomous model *action* on what it sees is explicitly out of scope (a later increment).

## Non-goals

- No new capture code: the native grab lives in coherence-membrane (`ScreenCaptureSource`).
- No autonomous model action on the live screen (perceive→gate→**act** over capture is later).
- No GPU-native path (Increment 3 -- RAW).
- No new third-party dependencies. coherence-membrane stays stdlib-only (ctypes).
- No streaming of raw screen pixels to the browser -- the shared medium is the *witnessed
  sight*, not the pixels.

## What already exists (consumed, not built)

- `coherence_membrane.native_capture.ScreenCaptureSource(region=None, source_id="screen")`
  → `.frames()` yields `Frame` (PNG payload); `grab_png(region)`; `capture_available() -> bool`;
  region = `(x, y, w, h)` or `None` (full primary display).
- `coherence_membrane.capture.CaptureSource` Protocol (`frames() -> Iterator[Frame]`),
  `Frame.read() -> bytes`, plus `IterableFrameSource` (for tests).
- `accountable_surface.world.sight.witness_image(png_bytes, *, cols) -> sight`
  (increment 1: shape + structure + OKLab colour + phash + digest).
- World SSE streaming (`/world/stream`, `World.subscribe()/_sse`) and the autopilot
  start/stop pattern (`run_autopilot`/`stop_autopilot`, `/autopilot` + `/autopilot/stop`,
  atomic check-and-set, daemon thread, bounded + stoppable) -- capture mirrors this exactly.
- Grant shape: `grant["scope"]["allowed_actions"]` (list). We add a sibling
  `allowed_perceptions` (list).

## Architecture & boundaries

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `src/accountable_surface/world/screen.py` | **Create (small)** | `witness_capture(source, *, max_frames, interval, sleep, should_stop, on_frame)` -- pull frames from any `CaptureSource`, witness each via `witness_image`, pace by `interval`, **change-proportional** (skip a frame whose phash == the previous), bound by `max_frames`, stop on `should_stop()`. Source-agnostic + deterministic (injectable `sleep`). Returns a session receipt dict. |
| `src/accountable_surface/world/session.py` | Modify | `screen_capture_allowed(grant) -> bool` (`"screen" in scope.allowed_perceptions`), default-deny. |
| `src/accountable_surface/world/server.py` | Modify | `World.run_capture(region, max_frames, interval)` (daemon thread, atomic check-and-set, streams `("capture", {...})`, appends a witnessed receipt); `World.stop_capture()`; POST `/capture/start` (`{region?, max_frames?, interval?}`) + `/capture/stop`. Fail-closed witnessed refusal if not granted or `capture_available()` is False. `_sandbox_grant` gains `allowed_perceptions` (default `[]`). |
| `web/screen.html` + `web/screen.js` | **Create** | Live spectator view: per `("capture", {frame_index, sight})` SSE event, render the witnessed sight -- ascii glyph grid + structure contours (reuse shipped `overlay.js` `drawContours`) + OKLab colour map (`renderColorMap`). Start/Stop controls + region inputs. |

Boundary rule kept: `screen.py` is source-agnostic and never imports a graphics API; the
world orchestrates and gates; coherence-membrane owns the platform grab.

### `screen.py` -- the witnessing loop (source-agnostic, deterministic)

```
witness_capture(source, *, max_frames, interval, sleep, should_stop, on_frame):
    last_phash = None
    emitted = 0
    for frame in source.frames():
        if should_stop() or emitted >= max_frames: break
        sight = witness_image(frame.read(), cols=...)
        if sight["phash"] == last_phash:        # change-proportional: skip unchanged
            sleep(interval); continue
        last_phash = sight["phash"]
        on_frame(frame.descriptor.frame_index, sight)   # stream + witness
        emitted += 1
        sleep(interval)
    return {"frames": emitted, ...}              # session receipt fields
```

- `sleep`/`should_stop` are injected so tests run with no real time and a deterministic stop.
- `source` is any `CaptureSource`; production passes `ScreenCaptureSource(region)`, tests pass
  `IterableFrameSource([png, png_dup, png2, ...])`.

## Data flow & the "same frame" (live)

```
operator grants 'screen' + POST /capture/start {region?, max_frames?, interval?}
  → gate: screen_capture_allowed(grant) AND capture_available()   [else witnessed refusal]
  → World.run_capture (daemon thread, atomic -- no two captures race):
        source = ScreenCaptureSource(region)
        witness_capture(source, ..., on_frame=lambda i, sight: _emit("capture", {i, sight}))
          each grab → witness_image → {ascii, structure, color, phash, digest}
          phash == last → skipped (no emit, no stream)
  → SSE ("capture", {frame_index, sight}) → web/screen.js renders ascii + contours + colour
  → bounded by max_frames; POST /capture/stop ends it; receipt witnesses region + count
```

The streamed object is the increment-1 witnessed sight, so structure + OKLab ride along and
every frame is digest/phash re-checkable. The model reads the current sight via the existing
chat/snapshot path; the spectator sees the same witnessed sight live -- the bilateral guarantee
from increment 1, now moving.

## Accountability (the weight of this increment)

- **Default-deny.** `allowed_perceptions` defaults `[]`. No grant → witnessed refusal, capture
  nothing. `capture_available()` False (no backend) → witnessed refusal, never a crash.
- **Two locks (defense in depth).** Capture runs only when *granted* AND *explicitly started*.
- **Witnessed session receipt.** Start (exact region: `[x,y,w,h]` or `"full-primary"`),
  per-frame digests (in the streamed sights), frame count, stop -- the capture is auditable
  like an action.
- **Bounded + stoppable + self-throttling.** `max_frames` + `interval` cap cost; `/capture/stop`
  ends it; change-proportional skipping avoids witnessing/streaming static frames.
- **Least-capture supported.** Optional region scopes what is seen; the receipt records exactly
  what was captured.

## Cadence / bounds (defaults)

- `interval = 1.0s` (calm, cheap; change-proportional skips static frames).
- `max_frames = 120` per session default; operator-overridable at start.
- Witnessing downscales as today (ascii `cols`; 128-wide structure field), so per-frame cost is
  bounded regardless of display resolution.

## Error handling (fail-closed)

- Not granted → `{"error": "perception 'screen' not granted", ...}`, witnessed refusal, HTTP 403-ish; capture nothing.
- `capture_available()` False → witnessed refusal naming the unsupported platform; never crash.
- A frame that fails to witness (undecodable grab) is skipped, not faked (same ethos as `sight_of`).
- A second `/capture/start` while one runs → refused (atomic check-and-set), not a race.
- Bad region (non-positive dims) → witnessed refusal from the backend, surfaced as a clean error.

## Testing

Targeted slice only: the new/affected world tests + the frontend node gate.

- **`tests/test_screen.py` (unit, NO real grab):**
  - Inject `IterableFrameSource` of known PNGs → witnessed sights carry `structure` + `color`.
  - **Change-proportional:** a repeated (identical) frame is skipped (phash equal) → fewer
    emits than frames.
  - `max_frames` honored (emits stop at the bound).
  - `should_stop()` flips → loop ends promptly.
  - `sleep` injected → no real wall-clock in tests.
- **Gate (`tests/test_world_*`):** `screen_capture_allowed` False without `'screen'`;
  `/capture/start` without the grant → witnessed refusal, no frames emitted; with the grant +
  an injected fake source → emits `("capture", …)` events and a receipt; `/capture/stop` ends it.
- **`capture_available()` False path:** monkeypatched → graceful witnessed refusal.
- **Spectator:** reuse the node-tested `overlay.js`; a small `screen.js` coord/render wiring is
  exercised by a **one-time controller Playwright live check** against a real granted capture
  session (controller runs it, like increment 1 -- confirms witnessed frames render live).

## Increment ladder (context)

- **Inc 1 (done):** the bilateral eye -- shape + structure + OKLab on uploads.
- **Inc 2 (this):** live, consent-gated, witnessed screen capture → the engine-agnostic eye.
- **Inc 3:** RAW -- GPU-native rendering depths.
- **Later:** the model autonomously acts on what it sees (perceive→gate→act over live capture).
