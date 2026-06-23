"""WorldSession — the body, alive in a world the operator co-inhabits.

Wraps an AccountableSurface + a bound FilesystemEffector + an operator grant, and turns one
PROPOSED action into one witnessed WorldStep through the REAL perceive -> gate -> act ->
re-perceive -> verify loop on real files under a sandbox root. The shared world reads
.snapshot() and streams .act() results: the model proposes, the gate decides, the hands act,
the receipt witnesses. Stdlib + the body's own organs only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path

from ..surface import AccountableSurface
from ..effector import FilesystemEffector, RefusedActuation
from .sight import sight_of
from .reel import load_reel

SIGHT_COLS = 96   # shared constant: columns used when rendering a PNG into the snapshot sight


@dataclass(frozen=True)
class WorldStep:
    """One witnessed turn of the loop — what the model proposed and what the body did about it."""
    kind: str
    target: str
    justification: str
    decision: str            # gate: allow | deny | needs-human
    acted: bool
    verified: bool
    verdict: str             # pass | failed | not-acted | refused-by-effector | ...
    before_digest: str
    after_digest: str | None
    rolled_back: bool
    reasons: list
    certificate: dict        # the composed Certificate (gate . effect . grounding)
    material: str            # the target's content AFTER the turn — what both now see
    reasoning: str = ""      # the proposer's voice: why this move (a model's narration, or "")

    def to_dict(self) -> dict:
        return asdict(self)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, IsADirectoryError, OSError):
        return ""


def _refused(kind: str, target: str, justification: str, reason: str, reasoning: str = "") -> WorldStep:
    """A witnessed refusal — a bad proposal becomes a recorded 'no', never a crash."""
    return WorldStep(kind, target, justification, "deny", False, False, "refused-by-effector",
                     "", None, False, [reason],
                     {"claim": f"action: {kind} {target}", "verdict": "refuted",
                      "oracle": "composed-v1", "evidence": [["refused", reason]]}, "", reasoning)


class WorldSession:
    """A live, bounded shared world: the model acts on real material under one sandbox root."""

    def __init__(self, root, grant, *, journal_path=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.grant = grant
        self.surface = AccountableSurface(journal_path=journal_path)
        self.fs = FilesystemEffector(self.root)
        self._focus: str | None = None
        self.reel = load_reel(self.root / "reel")   # moving material, if a reel/ of frames exists

    def _resolve(self, target: str) -> str:
        """Absolute path under root for `target`; refuse anything that escapes the world root."""
        p = Path(target).resolve() if os.path.isabs(target) else (self.root / target).resolve()
        if self.root != p and self.root not in p.parents:
            raise RefusedActuation(f"target {target!r} escapes the world root")
        return str(p)

    def act(self, *, kind, target, content="", justification="", reasoning="") -> WorldStep:
        """Run one proposed action through the body's loop and witness the result. Total: any
        proposal the surface can't honour becomes a witnessed refusal, never a crash."""
        if kind != "fs.write":
            return _refused(kind, target, justification,
                            f"unsupported action kind {kind!r} — this surface speaks fs.write", reasoning)
        try:
            tpath = self._resolve(target)
        except RefusedActuation as exc:
            return _refused(kind, target, justification, str(exc), reasoning)
        try:
            out = self.surface.actuate(self.fs, target=tpath, content=content.encode("utf-8"),
                                       authorization=self.grant, justification=justification or None)
        except RefusedActuation as exc:
            return _refused(kind, tpath, justification, str(exc), reasoning)
        if out.acted and out.verified:
            self._focus = tpath
        return WorldStep(kind, tpath, justification, out.decision, out.acted, out.verified,
                         out.verdict, out.before_digest, out.after_digest, out.rolled_back,
                         list(out.reasons), out.certificate, _read_text(tpath), reasoning)

    def snapshot(self) -> dict:
        """The shared world's current state: the material, what the model sees, and the journal."""
        files, sights, notes = [], [], {}
        try:
            if self.root.exists():
                for p in sorted(self.root.iterdir()):
                    if not p.is_file():
                        continue
                    files.append({"name": p.name, "size": p.stat().st_size})
                    if p.suffix.lower() == ".png":
                        seen = sight_of(p, cols=SIGHT_COLS)   # witnessed sight: shape + colour the model sees
                        if seen:
                            sights.append(seen)
                    elif p.suffix.lower() in (".md", ".txt") and len(notes) < 5:
                        notes[p.name] = _read_text(str(p))[:800]   # its own notes, to build on
        except OSError:
            files, sights, notes = [], [], {}   # a permission error -> an empty (not crashed) view
        focus = None
        if self._focus and Path(self._focus).is_file():
            focus = {"name": Path(self._focus).name, "content": _read_text(self._focus)}
        reel = None
        if self.reel:   # a light marker (count + one sampled frame); full frames served via /reel
            reel = {"count": self.reel["count"], "fps": self.reel["fps"],
                    "sample": self.reel["frames"][0]}
        scope = (self.grant or {}).get("scope", {})
        return {
            "root": str(self.root),
            "files": files,
            "sights": sights,
            "notes": notes,
            "reel": reel,
            "focus": focus,
            "journal": [e.to_dict() for e in self.surface.journal],
            "grant": {"allowed_actions": list(scope.get("allowed_actions", [])),
                      "allowed_targets": list(scope.get("allowed_targets", []))},
        }
