"""Operator-only durable authority CLI recovery controls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from accountable_surface.authority_state import DurableAuthorityState, request_fingerprint
from test_durable_authority_state import _grant


def _env():
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[1]
    paths = [str(root / "src"), str(root / "tests")]
    paths.extend(part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    return env


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "accountable_surface.authority_cli", *map(str, args)],
        check=True,
        capture_output=True,
        text=True,
        env=_env(),
    )


def test_cli_environment_preserves_configured_dependency_paths(monkeypatch, tmp_path):
    dependencies = [str(tmp_path / "coherence"), str(tmp_path / "proof")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(dependencies))

    paths = _env()["PYTHONPATH"].split(os.pathsep)

    assert paths[-2:] == dependencies


def test_operator_cli_releases_precommit_reservation_without_grant_body(tmp_path):
    state_path = tmp_path / "authority.sqlite3"
    grant = _grant(max_actions=1)
    state = DurableAuthorityState(state_path)
    reservation = state.reserve(grant, "fs.write", "k1", request_fingerprint({"target": "a"}), lease_seconds=-1)
    assert state.reserve(grant, "fs.write", "k2", request_fingerprint({"target": "b"})).reason == "authority-reservation-recovery-required"

    proc = _run_cli("recover-precommit", "--state", state_path, "--reservation-id", reservation.reservation_id, "--reason", "operator saw no commit")

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "released_precommit"
    assert "authorization-grant" not in proc.stdout
    assert DurableAuthorityState(state_path).reserve(grant, "fs.write", "k2", request_fingerprint({"target": "b"})).allowed is True


def test_operator_cli_records_durable_revocation(tmp_path):
    state_path = tmp_path / "authority.sqlite3"
    grant_path = tmp_path / "grant.json"
    grant = _grant()
    grant_path.write_text(json.dumps(grant), encoding="utf-8")

    proc = _run_cli("revoke", "--state", state_path, "--grant", grant_path, "--reason", "operator revoked")

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "revoked"
    assert DurableAuthorityState(state_path).reserve(grant, "fs.write", "k", "fp").reason == "operator grant is durably revoked"
