"""Live cross-language seam: really spawn telos native-control (Node) and gate it.

Skipped unless BOTH are present: a `node` on PATH and the native-control script, whose
path comes from the ACCOUNTABLE_SURFACE_NATIVE_CONTROL environment variable (an operator
supplies it; no local path is committed). When they are present this proves the same loop
the offline tests prove, but through a real subprocess: gate allow -> `device ls` via Node
-> the surface's independent witness confirms the actuator's listing -> MATCH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from accountable_surface.native_control_effector import NativeControlListEffector, NativeControlRunner
from accountable_surface.surface import AccountableSurface

_SCRIPT = os.environ.get("ACCOUNTABLE_SURFACE_NATIVE_CONTROL", "")
_HAVE_NODE = shutil.which("node") is not None
_HAVE_SCRIPT = bool(_SCRIPT) and Path(_SCRIPT).is_file()

pytestmark = pytest.mark.skipif(
    not (_HAVE_NODE and _HAVE_SCRIPT),
    reason="set ACCOUNTABLE_SURFACE_NATIVE_CONTROL to the native-control.mjs path and have node on PATH",
)


def _grant(actions):
    return {"authorization_version": "0.1", "receipt_id": "rcpt-live", "kind": "authorization-grant",
            "principal": {"id": "operator-1", "role": "operator"}, "agent": {"id": "nc-agent"},
            "intent": "native-control live read", "scope": {"allowed_actions": list(actions), "allowed_targets": []},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00", "revoked": False}


def test_live_device_ls_gated_and_verified(tmp_path):
    (tmp_path / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "two.txt").write_text("2", encoding="utf-8")
    (tmp_path / "child").mkdir()
    runner = NativeControlRunner(_SCRIPT)
    eff = NativeControlListEffector(runner, allowed_root=tmp_path)
    out = AccountableSurface().actuate(
        eff, target=str(tmp_path), content=[str(tmp_path)], authorization=_grant(["native.device.ls"])
    )
    assert out.acted is True
    assert out.verified is True   # real Node listing matched the surface's own witness
    assert eff.native_control_receipt()["schema"] == "project-telos.native-control/v1"
