"""Per-target tiers (R6): what an action class may do to one target.

Modeled on the computer-use grant tiers and applied per target: an origin on the
browser and web paths, a window on the desktop path.

    read   perceive, find, screenshot, region capture
    click  read plus invoke, click, navigate, submit, scroll, hover, select
    full   click plus fill, set_value, a scoped key send, drag, upload

Separate flags, off by default: `clipboard_read`, `clipboard_write`,
`system_keys`, `upload_root`.

The grant names tiers in `scope.target_tiers`, an accountable-surface field that
`grant.action_authorization` strips before the grant reaches proof-surface's
closed schema. (The design proposed `allowed_targets`, but proof-surface already
owns that name for its target allowlist, so reusing it would have changed what
the gate matches.)

Class ceilings live in code and a grant can only narrow them: a browser window
on the desktop path is `read` (browser work goes through the browser effector),
a terminal or IDE is `click`, a credential or security surface is `read`. A
window binds to the pair (title, process image path), because any window can
copy a title.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

TIERS = ("read", "click", "full")
_RANK = {t: i for i, t in enumerate(TIERS)}
REQUIRED = {
    "perceive": "read", "find": "read", "screenshot": "read", "capture": "read", "ls": "read",
    "navigate": "click", "click": "click", "submit": "click", "invoke": "click", "select": "click",
    "scroll": "click", "hover": "click",
    "fill": "full", "set_value": "full", "key": "full", "drag": "full", "upload": "full",
    "evaluate": "full", "write": "full", "run": "full",
}
FLAGS = {"clipboard.read": "clipboard_read", "clipboard.write": "clipboard_write",
         "desktop.system_key": "system_keys", "browser.upload": "upload_root"}
BROWSERS = frozenset({"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
                      "vivaldi.exe", "iexplore.exe", "arc.exe", "safari"})
TERMINALS = frozenset({"windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
                       "code.exe", "idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe",
                       "devenv.exe", "wt.exe", "bash.exe", "wsl.exe"})
SECURITY = frozenset({"consent.exe", "credentialuibroker.exe", "securityhealthui.exe",
                      "1password.exe", "keepass.exe", "keepassxc.exe", "bitwarden.exe",
                      "lockapp.exe", "logonui.exe"})


@dataclass(frozen=True)
class TierCheck:
    allowed: bool
    granted: str | None
    ceiling: str
    required: str
    effective: str | None
    reason: str | None

    def to_dict(self) -> dict:
        return {"granted": self.granted, "ceiling": self.ceiling, "required": self.required,
                "effective": self.effective}


def required_tier(action_kind: str) -> str:
    """The tier an action class needs. Unknown classes need `full`."""
    if action_kind.startswith(("api.", "fs.", "os.")):
        return "full"
    if action_kind in FLAGS:
        return "full"
    return REQUIRED.get(action_kind.rsplit(".", 1)[-1], "full")


def _image_base(path: str) -> str:
    return os.path.basename(str(path).replace("\\", "/")).lower()


def ceiling(target: dict) -> str:
    """The class ceiling for a target, fixed in code."""
    window = target.get("window") if isinstance(target, dict) else None
    if not isinstance(window, dict):
        return "full"
    base = _image_base(window.get("image", ""))
    if base in BROWSERS or base in SECURITY:
        return "read"
    if base in TERMINALS:
        return "click"
    return "full"


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path).replace("\\", "/")))


def _entry_for(target: dict, grant) -> tuple[dict | None, str | None]:
    scope = grant.get("scope") if isinstance(grant, dict) else None
    entries = scope.get("target_tiers") if isinstance(scope, dict) else None
    if not isinstance(entries, list):
        return None, "grant names no target_tiers"
    if "origin" in target:
        want = str(target["origin"]).rstrip("/").lower()
        hit = next((e for e in entries if isinstance(e, dict) and str(e.get("origin", "")).rstrip("/").lower() == want), None)
        return hit, None if hit else f"no tier granted for origin {want!r}"
    window = target.get("window") or {}
    titled = [e for e in entries if isinstance(e, dict) and isinstance(e.get("window"), dict)
              and e["window"].get("title") == window.get("title")]
    hit = next((e for e in titled if _norm_path(e["window"].get("image", "")) == _norm_path(window.get("image", ""))), None)
    if hit is None and titled:
        return None, "window title matches a grant but the process image differs"
    return hit, None if hit else "no tier granted for this window"


def check(action_kind: str, target: dict, grant) -> TierCheck:
    """Whether the grant's tier for this target, capped by the class ceiling,
    covers the action class and any flag it needs."""
    required, cap = required_tier(action_kind), ceiling(target)
    entry, reason = _entry_for(target if isinstance(target, dict) else {}, grant)
    granted = entry.get("tier") if entry else None
    if granted not in _RANK:
        why = reason or f"granted tier {granted!r} is not one of {TIERS}"
        return TierCheck(False, granted, cap, required, None, why)
    effective = TIERS[min(_RANK[granted], _RANK[cap])]
    if _RANK[effective] < _RANK[required]:
        return TierCheck(False, granted, cap, required, effective,
                         f"{action_kind} needs {required}; this target allows {effective}")
    flag = FLAGS.get(action_kind)
    if flag and not entry.get(flag):
        return TierCheck(False, granted, cap, required, effective, f"{action_kind} needs the {flag} flag")
    return TierCheck(True, granted, cap, required, effective, None)
