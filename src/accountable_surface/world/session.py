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

    def _resolve(self, target: str) -> str:
        """Absolute path under root for `target`; refuse anything that escapes the world root."""
        p = Path(target).resolve() if os.path.isabs(target) else (self.root / target).resolve()
        if self.root != p and self.root not in p.parents:
            raise RefusedActuation(f"target {target!r} escapes the world root")
        return str(p)

    def act(self, *, kind, target, content="", justification="", reasoning="") -> WorldStep:
        """Run one proposed action through the body's loop and witness the result."""
        if kind != "fs.write":
            raise ValueError(f"unsupported action kind {kind!r} (this surface speaks fs.write)")
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
        """The shared world's current state: the material, the focus, the witnessed journal."""
        files = []
        if self.root.exists():
            for p in sorted(self.root.iterdir()):
                if p.is_file():
                    files.append({"name": p.name, "size": p.stat().st_size})
        focus = None
        if self._focus and Path(self._focus).is_file():
            focus = {"name": Path(self._focus).name, "content": _read_text(self._focus)}
        scope = (self.grant or {}).get("scope", {})
        return {
            "root": str(self.root),
            "files": files,
            "focus": focus,
            "journal": [e.to_dict() for e in self.surface.journal],
            "grant": {"allowed_actions": list(scope.get("allowed_actions", [])),
                      "allowed_targets": list(scope.get("allowed_targets", []))},
        }
