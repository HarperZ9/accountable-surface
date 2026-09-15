"""Durable remote protected-path controls."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from accountable_surface.protected_paths import ProtectedPaths
from accountable_surface.remote_actuation import actuate_impl
from accountable_surface.server import AuthorityStore
from accountable_surface.surface import AccountableSurface
from test_durable_authority_remote import (
    CountingFilesystemEffector,
    _grant,
    _registry,
    _write_grants,
)


def _snapshot(path):
    return path.read_bytes() if path.exists() else None


def _hardlink_or_skip(original, link):
    try:
        os.link(original, link)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable for this test filesystem: {exc}")
    try:
        assert os.path.samefile(original, link)
    except OSError as exc:
        pytest.skip(f"hardlink identity unavailable for this test filesystem: {exc}")


def _sqlite_state_with_sidecars(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS t(x)")
    conn.commit()
    return conn


def test_protected_path_identity_lookup_error_fails_closed(tmp_path, monkeypatch):
    protected = tmp_path / "grants.json"
    candidate = tmp_path / "candidate"
    protected.write_text("grant", encoding="utf-8")
    candidate.write_text("candidate", encoding="utf-8")
    original_samefile = os.path.samefile
    original_stat = Path.stat

    def samefile_with_indeterminate_identity(left, right):
        if Path(left) == candidate and Path(right) == protected:
            raise OSError("identity unavailable")
        return original_samefile(left, right)

    def stat_with_indeterminate_identity(self, *args, **kwargs):
        if self in {candidate, protected}:
            raise OSError("identity unavailable")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(os.path, "samefile", samefile_with_indeterminate_identity)
    monkeypatch.setattr(Path, "stat", stat_with_indeterminate_identity)

    hit = ProtectedPaths([protected]).deny_path(candidate)

    assert hit is not None
    assert hit.requested == str(candidate)


@pytest.mark.parametrize("target_kind", ["grants", "authority-db", "journal", "authority-wal", "authority-shm"])
def test_hardlinked_protected_paths_refuse_before_read_and_write(tmp_path, target_kind):
    root = tmp_path / "root"
    root.mkdir()
    grants_path = root / "grants.json"
    state_path = root / "authority.sqlite3"
    journal_path = root / "journal.jsonl"
    grant = _grant(root, max_actions=50)
    _write_grants(grants_path, [grant])
    journal_path.write_text("journal-original", encoding="utf-8")
    state_conn = _sqlite_state_with_sidecars(state_path)
    try:
        original = {
            "grants": grants_path,
            "authority-db": state_path,
            "journal": journal_path,
            "authority-wal": Path(str(state_path) + "-wal"),
            "authority-shm": Path(str(state_path) + "-shm"),
        }[target_kind]
        link = root / f"{target_kind}-hardlink"
        _hardlink_or_skip(original, link)
        before = _snapshot(original)
        store = AuthorityStore(str(grants_path), authority_state_path=str(state_path), journal_path=str(journal_path))
        effector = CountingFilesystemEffector(root)

        try:
            out = actuate_impl(
                AccountableSurface(), store, _registry(root, effector), "fs.write",
                str(link), "overwrite-hardlink", idempotency_key=f"hardlink-{target_kind}",
            )
        except Exception as exc:  # noqa: BLE001 - red control reports escaped state corruption.
            out = {"decision": "exception", "exception": f"{type(exc).__name__}: {exc}"}

        assert out["decision"] == "deny"
        assert "protected authority path" in out["reasons"][0]
        assert effector.perceives == 0
        assert effector.writes == 0
        assert _snapshot(original) == before
    finally:
        state_conn.close()


@pytest.mark.parametrize("token", ["%2E", "%2F", "%5C"])
@pytest.mark.parametrize("target_kind", ["grants", "authority-db", "authority-wal", "authority-shm"])
def test_literal_percent_escaped_protected_paths_refuse_before_read_and_write(tmp_path, token, target_kind):
    root = tmp_path / "root"
    root.mkdir()
    grants_path = root / (f"operator{token}grants.json" if target_kind == "grants" else "grants.json")
    state_path = root / (f"authority{token}sqlite3" if target_kind != "grants" else "authority.sqlite3")
    grant = _grant(root, max_actions=50)
    _write_grants(grants_path, [grant])
    target = {
        "grants": grants_path,
        "authority-db": state_path,
        "authority-wal": Path(str(state_path) + "-wal"),
        "authority-shm": Path(str(state_path) + "-shm"),
    }[target_kind]
    before = _snapshot(target)
    store = AuthorityStore(str(grants_path), authority_state_path=str(state_path))
    effector = CountingFilesystemEffector(root)

    out = actuate_impl(
        AccountableSurface(), store, _registry(root, effector), "fs.write",
        str(target), "overwrite", idempotency_key=f"literal-{target_kind}-{token}",
    )

    assert out["decision"] == "deny"
    assert "protected authority path" in out["reasons"][0]
    assert effector.perceives == 0
    assert effector.writes == 0
    assert _snapshot(target) == before
