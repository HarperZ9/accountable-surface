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
        if sight["digest"] == last_phash:
            sleep(interval)
            continue  # change-proportional: nothing new to witness
        last_phash = sight["digest"]
        on_frame(frame.descriptor.frame_index, sight)
        emitted += 1
        sleep(interval)
    return {"frames": emitted, "stopped": stopped}
