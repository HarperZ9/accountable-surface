"""Tests for the efferent arm -- FilesystemEffector (Phase 5).

Offline. Proves an effector is **inert until authorized** (no gate allow -> refuses,
writes nothing), **bounded** to its construction root, **reversible**, and that it
witnesses + can self-verify its own work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from accountable_surface.effector import FilesystemEffector, RefusedActuation


class _Allow:
    """Stand-in gate allow receipt, matching the surface's ActionOutcome shape."""

    decision = "allow"

    def __init__(self, action_kind: str, target: str):
        self.request = {"planned_action": {"action_kind": action_kind, "target": target}}


def test_perceive_absent_then_present(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    assert eff.perceive(target).data["exists"] is False
    Path(target).write_bytes(b"hi")
    obs = eff.perceive(target)
    assert obs.data["exists"] is True
    assert obs.data["size"] == 2


def test_preview_describes_the_write(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    plan = eff.preview(target, b"hello")
    assert plan.action_kind == "fs.write"
    assert plan.target == target
    assert plan.reversible is True
    assert plan.existed_before is False
    assert plan.digest.startswith("sha256:")


def test_act_without_allow_refuses_and_writes_nothing(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    plan = eff.preview(target, b"hello")
    with pytest.raises(RefusedActuation):
        eff.act(plan, allow_receipt=None, content=b"hello")
    assert not Path(target).exists()  # the doctrine: no allow -> no effect


def test_act_with_allow_writes_and_witnesses(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    plan = eff.preview(target, b"hello")
    post = eff.act(plan, _Allow("fs.write", target), content=b"hello")
    assert Path(target).read_bytes() == b"hello"
    assert post.data["sha256"] == plan.content_sha256


def test_act_refuses_outside_root(tmp_path):
    (tmp_path / "sandbox").mkdir()
    eff = FilesystemEffector(tmp_path / "sandbox")
    outside = str(tmp_path / "escape.txt")
    plan = eff.preview(outside, b"x")
    with pytest.raises(RefusedActuation):
        eff.act(plan, _Allow("fs.write", outside), content=b"x")
    assert not Path(outside).exists()  # bounded by construction, even with an allow


def test_act_refuses_content_not_matching_plan(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    plan = eff.preview(target, b"intended")
    with pytest.raises(RefusedActuation):
        eff.act(plan, _Allow("fs.write", target), content=b"DIFFERENT")
    assert not Path(target).exists()


def test_verify_pass_then_fail(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    plan = eff.preview(target, b"hello")
    eff.act(plan, _Allow("fs.write", target), content=b"hello")
    assert eff.verify(plan, eff.perceive(target)).status == "pass"
    Path(target).write_bytes(b"tampered")  # out-of-band change
    assert eff.verify(plan, eff.perceive(target)).status == "failed"


def test_rollback_restores_prior_content(tmp_path):
    eff = FilesystemEffector(tmp_path)
    target = str(tmp_path / "f.txt")
    Path(target).write_bytes(b"original")
    plan = eff.preview(target, b"replacement")
    eff.act(plan, _Allow("fs.write", target), content=b"replacement")
    assert Path(target).read_bytes() == b"replacement"
    eff.rollback(plan)
    assert Path(target).read_bytes() == b"original"  # reversible


def test_selftest_holds(tmp_path):
    assert FilesystemEffector(tmp_path).selftest() is True
