"""Per-effector grant scope -- can the grant bound how far a gate allow travels?

Before `allowed_bounds`, the answer was no. A grant naming `fs.write` with an empty
`allowed_targets` placed no bound on the target at all; the only thing stopping a
write outside the intended root was the effector's own constructor. Build the
effector wider and the SAME unchanged grant reached further, and the journal
recorded both actuations identically, so an auditor could not tell them apart.

These tests hold the grant fixed and move the effector.
"""

from __future__ import annotations

from pathlib import Path

from accountable_surface.bounds import bound_of, bound_refusal, entry_covers, render_bound
from accountable_surface.browser_effector import BrowserEffector, FakeBrowserDriver
from accountable_surface.effector import FilesystemEffector
from accountable_surface.os_effector import CommandEffector
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import FakePageDriver, WebEffector


def _grant(actions, targets=(), bounds=None):
    scope = {"allowed_actions": list(actions), "allowed_targets": list(targets)}
    if bounds is not None:
        scope["allowed_bounds"] = list(bounds)
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-bound-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "bound-agent"},
        "intent": "bounded actuation test",
        "scope": scope,
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


class _FakeRunner:
    def run(self, argv, cwd):
        return {"exit_code": 0, "stdout": "", "stderr": ""}


# --- every shipped effector declares its bound ------------------------------


def test_filesystem_effector_declares_its_root(tmp_path):
    assert bound_of(FilesystemEffector(tmp_path)) == {"kind": "fs", "root": tmp_path.resolve().as_posix()}


def test_command_effector_declares_cwd_and_allowlist(tmp_path):
    bound = bound_of(CommandEffector(_FakeRunner(), {"ls", "echo"}, tmp_path))
    assert bound == {"kind": "os", "cwd": tmp_path.resolve().as_posix(), "commands": ["echo", "ls"]}


def test_web_effector_declares_its_origins():
    bound = bound_of(WebEffector(FakePageDriver(), ["https://b.test/", "https://a.test"]))
    assert bound == {"kind": "web", "origins": ["https://a.test", "https://b.test"]}


def test_browser_effector_declares_its_origins():
    bound = bound_of(BrowserEffector(FakeBrowserDriver(), ["https://a.test"]))
    assert bound == {"kind": "browser", "origins": ["https://a.test"]}


def test_an_effector_without_a_bound_declares_none():
    class Anonymous:
        pass

    assert bound_of(Anonymous()) is None


# --- coverage is containment, and it fails closed ---------------------------


def test_a_granted_path_covers_itself_and_anything_under_it():
    granted = {"kind": "fs", "root": "/work"}
    assert entry_covers(granted, {"kind": "fs", "root": "/work"})
    assert entry_covers(granted, {"kind": "fs", "root": "/work/project"})


def test_a_wider_effector_root_is_not_covered():
    """The finding: widening the root must stop the grant from matching."""
    assert not entry_covers({"kind": "fs", "root": "/work/project"}, {"kind": "fs", "root": "/work"})


def test_a_sibling_path_sharing_a_prefix_is_not_covered():
    """String-prefix containment would wrongly accept /workshop under /work."""
    assert not entry_covers({"kind": "fs", "root": "/work"}, {"kind": "fs", "root": "/workshop"})


def test_a_set_facet_is_covered_only_as_a_subset():
    granted = {"kind": "os", "cwd": "/w", "commands": ["echo", "ls"]}
    assert entry_covers(granted, {"kind": "os", "cwd": "/w", "commands": ["echo"]})
    assert not entry_covers(granted, {"kind": "os", "cwd": "/w", "commands": ["echo", "rm"]})


def test_a_different_kind_is_never_covered():
    assert not entry_covers({"kind": "web", "origins": ["https://a.test"]},
                            {"kind": "browser", "origins": ["https://a.test"]})


def test_a_facet_the_grant_does_not_mention_is_not_covered():
    """An os bound reaches through cwd AND the allowlist; a grant naming only cwd
    has not spoken about the allowlist, so it cannot cover it."""
    assert not entry_covers({"kind": "os", "cwd": "/w"}, {"kind": "os", "cwd": "/w", "commands": ["ls"]})


def test_an_unknown_facet_name_is_not_covered():
    """A facet this module cannot reason about must fail closed, never silently pass."""
    assert not entry_covers({"kind": "fs", "depth": 3}, {"kind": "fs", "depth": 3})


def test_render_bound_is_stable_and_names_the_undeclared_case():
    assert render_bound({"kind": "os", "cwd": "/w", "commands": ["ls", "echo"]}) == "os:commands=echo,ls cwd=/w"
    assert render_bound(None) == "undeclared"


# --- the grant field is only enforced when the operator writes it -----------


def test_a_grant_that_says_nothing_about_bounds_does_not_refuse(tmp_path):
    """Honest null: absent `allowed_bounds` places no bound on the effector."""
    assert bound_refusal(_grant(["fs.write"]), FilesystemEffector(tmp_path)) is None


def test_an_effector_with_no_bound_is_refused_once_bounds_are_named():
    class Anonymous:
        pass

    reason = bound_refusal(_grant(["fs.write"], bounds=[{"kind": "fs", "root": "/w"}]), Anonymous())
    assert reason is not None and "declares no bound" in reason


def test_the_refusal_names_the_effector_bound_the_operator_has_to_grant(tmp_path):
    reason = bound_refusal(_grant(["fs.write"], bounds=[{"kind": "fs", "root": "/elsewhere"}]),
                           FilesystemEffector(tmp_path))
    assert reason is not None and tmp_path.resolve().as_posix() in reason


# --- through the whole loop: one grant, two effectors -----------------------


def test_the_same_grant_allows_the_narrow_effector_and_denies_the_wider_one(tmp_path):
    """Case 3 vs case 5 of the probe that motivated this field. The grant never
    changes; only the effector's construction bound does."""
    narrow_root = tmp_path / "project"
    narrow_root.mkdir()
    grant = _grant(["fs.write"], bounds=[{"kind": "fs", "root": narrow_root.resolve().as_posix()}])
    target = str(narrow_root / "f.txt")

    surface = AccountableSurface()
    inside = surface.actuate(FilesystemEffector(narrow_root), target=target, content=b"hi",
                             authorization=grant)
    assert inside.decision == "allow" and inside.acted is True and inside.verified is True

    escaped = str(tmp_path / "outside.txt")
    wide = surface.actuate(FilesystemEffector(tmp_path), target=escaped, content=b"hi",
                           authorization=grant)
    assert wide.decision == "deny"
    assert wide.verdict == "bound-not-granted"
    assert wide.acted is False
    assert not Path(escaped).exists()


def test_the_journal_tells_the_narrow_actuation_from_the_wide_one(tmp_path):
    """The auditor-visible half of the finding: two actuations that used to record
    identically now carry the bound each one acted under."""
    inner = tmp_path / "inner"
    inner.mkdir()
    grant = _grant(["fs.write"])  # no allowed_bounds -- both are permitted
    surface = AccountableSurface()
    surface.actuate(FilesystemEffector(inner), target=str(inner / "a.txt"), content=b"a",
                    authorization=grant)
    surface.actuate(FilesystemEffector(tmp_path), target=str(tmp_path / "b.txt"), content=b"b",
                    authorization=grant)
    bounds = [e.detail["effector_bound"] for e in surface.journal if e.kind == "actuation"]
    assert bounds == [f"fs:root={inner.resolve().as_posix()}", f"fs:root={tmp_path.resolve().as_posix()}"]


def test_allowed_bounds_never_reaches_the_closed_gate_schema(tmp_path):
    """proof-surface's action-authorization schema rejects any unexpected scope field.
    An allow here proves actuate stripped it, the way it strips allowed_perceptions."""
    grant = _grant(["fs.write"], bounds=[{"kind": "fs", "root": tmp_path.resolve().as_posix()}])
    out = AccountableSurface().actuate(FilesystemEffector(tmp_path), target=str(tmp_path / "f.txt"),
                                       content=b"hi", authorization=grant)
    assert out.decision == "allow"
    assert not any("unexpected field" in r for r in out.reasons)


def test_a_bounded_command_grant_does_not_cover_a_wider_allowlist(tmp_path):
    """os.run reach is cwd AND the allowlist; widening either one loses the grant."""
    grant = _grant(["os.run"], bounds=[{"kind": "os", "cwd": tmp_path.resolve().as_posix(),
                                        "commands": ["echo"]}])
    wide = CommandEffector(_FakeRunner(), {"echo", "rm"}, tmp_path)
    out = AccountableSurface().actuate(wide, target="probe", content=["echo", "hi"],
                                       authorization=grant, allow_irreversible=True)
    assert out.decision == "deny" and out.verdict == "bound-not-granted"
