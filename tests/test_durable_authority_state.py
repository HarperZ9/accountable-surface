"""SQLite-backed durable authority-state controls.

These tests use only synthetic grant records and temp files. They are designed to
fail if usage and idempotency are merely checked in process memory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

import pytest

from accountable_surface.authority_state import (
    AuthorityStateError,
    DurableAuthorityState,
    grant_ref,
    request_fingerprint,
)


def _grant(receipt="rcpt-durable", nonce="nonce-1", max_actions=1):
    return {
        "authorization_version": "0.1",
        "receipt_id": receipt,
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "mcp-caller"},
        "intent": "durable authority test",
        "scope": {"allowed_actions": ["fs.write"], "max_actions": max_actions},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
        "nonce": nonce,
    }


def _fp(grant, target="target.txt", payload="hello"):
    return request_fingerprint({
        "action_kind": "fs.write",
        "target": target,
        "content_sha256": payload,
        "grant_ref": grant_ref(grant),
    })


def test_same_idempotency_key_with_different_request_refuses_without_new_usage(tmp_path):
    state = DurableAuthorityState(tmp_path / "authority.sqlite3")
    grant = _grant(max_actions=2)
    first = state.reserve(grant, "fs.write", "repeat-key", _fp(grant, "a.txt"))
    assert first.allowed is True
    state.commit_to_act(first.reservation_id, grant)
    state.finish(first.reservation_id, "succeeded", "sha256:first")

    second = state.reserve(grant, "fs.write", "repeat-key", _fp(grant, "b.txt"))

    assert second.allowed is False
    assert second.reason == "idempotency-conflict"
    usage = state.usage_for(grant)
    assert usage["counted"] == 1


def _reserve_worker(db_path, grant_json, key, payload, out_path):
    from accountable_surface.authority_state import DurableAuthorityState, request_fingerprint

    grant = json.loads(grant_json)
    state = DurableAuthorityState(db_path, busy_timeout=1.0)
    try:
        result = state.reserve(grant, "fs.write", key, request_fingerprint({"payload": payload}))
        if result.allowed:
            state.commit_to_act(result.reservation_id, grant)
            state.finish(result.reservation_id, "succeeded", "sha256:" + payload)
        payload_out = {"allowed": result.allowed, "reason": result.reason}
    except Exception as exc:
        payload_out = {"allowed": False, "reason": str(exc)}
    Path(out_path).write_text(json.dumps(payload_out), encoding="utf-8")


def test_concurrent_processes_cannot_double_spend_one_action(tmp_path):
    import multiprocessing as mp

    grant = _grant(max_actions=1)
    db_path = tmp_path / "authority.sqlite3"
    outputs = [tmp_path / "a.json", tmp_path / "b.json"]
    ctx = mp.get_context("spawn")
    DurableAuthorityState(db_path).recovery_report()
    processes = [
        ctx.Process(target=_reserve_worker, args=(str(db_path), json.dumps(grant), f"k-{i}", str(i), str(outputs[i])))
        for i in range(2)
    ]
    for proc in processes:
        proc.start()
    for proc in processes:
        proc.join(10)
        assert proc.exitcode == 0

    results = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
    assert sum(1 for result in results if result["allowed"]) == 1
    assert sum(1 for result in results if result["reason"] in {"usage-exhausted", "authority-state-busy"}) == 1
    assert DurableAuthorityState(db_path).usage_for(grant)["counted"] == 1


def test_two_process_sqlite_contention_fails_closed(tmp_path):
    db_path = tmp_path / "authority.sqlite3"
    ready = tmp_path / "locked.ready"
    locker = subprocess.Popen([
        sys.executable,
        "-c",
        dedent(
            """
            import sqlite3, sys, time
            db, ready = sys.argv[1], sys.argv[2]
            conn = sqlite3.connect(db, timeout=5.0)
            conn.execute('CREATE TABLE IF NOT EXISTS held (id INTEGER)')
            conn.execute('BEGIN IMMEDIATE')
            open(ready, 'w', encoding='utf-8').write('ready')
            time.sleep(5)
            """
        ),
        str(db_path),
        str(ready),
    ])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        assert ready.exists()
        with pytest.raises(AuthorityStateError, match="authority-state-busy"):
            DurableAuthorityState(db_path, busy_timeout=0.05).reserve(_grant(), "fs.write", "blocked", "fp")
    finally:
        locker.terminate()
        locker.wait(timeout=5)



def _child_env():
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[1]
    extra = os.pathsep.join([str(root / "src"), str(root / "tests")])
    env["PYTHONPATH"] = extra + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _crash_script(state_name):
    return dedent(
        f"""
        import json, os, sys
        from pathlib import Path
        from accountable_surface.authority_state import DurableAuthorityState, request_fingerprint
        db, grant_path, rid_path = map(Path, sys.argv[1:4])
        grant = json.loads(grant_path.read_text(encoding='utf-8'))
        state = DurableAuthorityState(db, busy_timeout=1.0)
        reservation = state.reserve(grant, 'fs.write', 'crash-key', request_fingerprint({{'case': '{state_name}'}}), lease_seconds=-1)
        rid_path.write_text(reservation.reservation_id or '', encoding='utf-8')
        {'state.commit_to_act(reservation.reservation_id, grant)' if state_name == 'committed' else ''}
        os._exit(9)
        """
    )


def test_reserved_precommit_crash_counts_until_operator_release(tmp_path):
    grant = _grant(max_actions=1)
    grant_path = tmp_path / "grant.json"
    grant_path.write_text(json.dumps(grant), encoding="utf-8")
    rid_path = tmp_path / "reservation.txt"
    subprocess.run([sys.executable, "-c", _crash_script("reserved"), str(tmp_path / "state.sqlite3"), str(grant_path), str(rid_path)], check=False, env=_child_env())

    state = DurableAuthorityState(tmp_path / "state.sqlite3")
    report = state.recovery_report()
    assert report["reserved_precommit"] == 1
    blocked = state.reserve(grant, "fs.write", "new-key", _fp(grant, "after-crash"))
    assert blocked.reason == "authority-reservation-recovery-required"

    state.release_precommit(rid_path.read_text(encoding="utf-8"), "operator verified no commit_to_act record")
    assert state.reserve(grant, "fs.write", "new-key", _fp(grant, "after-crash")).allowed is True


def test_committed_crash_stays_ambiguous_and_spent(tmp_path):
    grant = _grant(max_actions=1)
    grant_path = tmp_path / "grant.json"
    grant_path.write_text(json.dumps(grant), encoding="utf-8")
    rid_path = tmp_path / "reservation.txt"
    subprocess.run([sys.executable, "-c", _crash_script("committed"), str(tmp_path / "state.sqlite3"), str(grant_path), str(rid_path)], check=False, env=_child_env())

    state = DurableAuthorityState(tmp_path / "state.sqlite3")
    report = state.recovery_report()
    assert report["committed_in_flight"] == 1
    repeat = state.reserve(grant, "fs.write", "crash-key", request_fingerprint({"case": "committed"}))
    assert repeat.allowed is False
    assert repeat.reason == "operation-ambiguous"
    assert state.reserve(grant, "fs.write", "other-key", _fp(grant, "other")).reason == "usage-exhausted"


def test_corrupt_sqlite_state_refuses_unverifiable(tmp_path):
    db_path = tmp_path / "authority.sqlite3"
    db_path.write_bytes(b"not a sqlite database")
    with pytest.raises(AuthorityStateError, match="authority-state-unverifiable"):
        DurableAuthorityState(db_path).reserve(_grant(), "fs.write", "k", "fp")
