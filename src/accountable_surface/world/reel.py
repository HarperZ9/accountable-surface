"""A reel -- moving material the model and a spectator both watch as ASCII frames.

A directory of image frames (e.g. extracted from a GIF or video) becomes a sequence of witnessed
glyph grids: each frame the same shared sight, played in order. The spectator watches an ASCII
animation; the model perceives the moving material a frame at a time. Composes the same witnessed
sight (decode_png + ascii_view); loaded once, then cheap to serve. Stdlib + coherence-membrane only.
"""
from __future__ import annotations

from pathlib import Path

from .sight import witness_image


def load_reel(reel_dir, *, cols: int = 56, fps: int = 8) -> dict | None:
    """Load a directory of PNG frames into a playable reel of witnessed ASCII frames, or None if
    there are no decodable frames (no reel != a broken one)."""
    d = Path(reel_dir)
    if not d.is_dir():
        return None
    frames = []
    for p in sorted(d.iterdir()):
        if not (p.is_file() and p.suffix.lower() == ".png"):
            continue
        try:
            frames.append({"name": p.name, **witness_image(p.read_bytes(), cols=cols)})
        except Exception:
            continue  # an undecodable frame is skipped, not faked
    if not frames:
        return None
    return {"count": len(frames), "fps": fps, "frames": frames}
