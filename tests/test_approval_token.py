"""Human confirmation: pending approvals, the console-bound approve CLI, pauses.

A `confirm` writes a pending approval and returns no token. A person approves in
their own terminal; the CLI re-renders the step from the stored record and asks
the person to type the action verb and the target host at an interactive
console. The approval is an HMAC over the approval id, step digest, before
digest, expiry, and a nonce, keyed by a file the model's tools never read. It is
single use and voided by any change to the step or the page.
"""

from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from accountable_surface import authority_cli
from accountable_surface.approvals import ApprovalStore

SRC = Path(__file__).resolve().parent.parent / "src"
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
RENDER = {"action_kind": "web.submit", "target": {"origin": "http://127.0.0.1:8765", "path": "/order",
                                                  "control": {"name": "Submit order"}}}


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class Console:
    def __init__(self, *answers):
        self.answers, self.shown = list(answers), []

    def show(self, text):
        self.shown.append(text)

    def ask(self, prompt):
        self.shown.append(prompt)
        return self.answers.pop(0)


@pytest.fixture
def store(tmp_path):
    return ApprovalStore(tmp_path / "authority.db", clock=Clock())


def _approve(store, approval_id, *answers):
    answers = answers or ("submit", "127.0.0.1:8765")
    authority_cli.main(["approve", "--state", str(store.path), "--approval-id", approval_id,
                        "--approver", "operator"], console=Console(*answers), clock=store.clock)


def test_pending_approval_carries_a_rendering_and_no_token(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    [pending] = store.pending()
    assert pending["approval_id"] == aid and pending["rendering"] == RENDER
    assert "token" not in pending and "nonce" not in pending
    assert "accountable-surface-authority approve" in pending["command"]
    assert store.request("sha256:x", "sha256:p", "sha256:b", RENDER) == aid  # one pending per step and page


def test_approval_for_x_never_authorizes_y(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    _approve(store, aid)
    assert store.live_for("sha256:x", "sha256:b")["approval_id"] == aid
    assert store.live_for("sha256:y", "sha256:b") is None


def test_approval_is_single_use(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    _approve(store, aid)
    assert store.consume(aid, "sha256:x", "sha256:b") is True
    assert store.consume(aid, "sha256:x", "sha256:b") is False
    assert store.live_for("sha256:x", "sha256:b") is None


def test_expired_approval_refuses(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    _approve(store, aid)
    store.clock.now = T0 + timedelta(minutes=11)
    assert store.live_for("sha256:x", "sha256:b") is None
    assert store.consume(aid, "sha256:x", "sha256:b") is False


def test_changed_before_digest_voids_the_approval(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    _approve(store, aid)
    assert store.live_for("sha256:x", "sha256:changed") is None
    assert store.consume(aid, "sha256:x", "sha256:changed") is False


def test_wrong_answers_at_the_console_approve_nothing(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    with pytest.raises(SystemExit):
        _approve(store, aid, "submit", "evil.example")
    assert store.live_for("sha256:x", "sha256:b") is None
    assert store.pending()[0]["approval_id"] == aid


def test_deny_closes_the_request(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    authority_cli.main(["deny", "--state", str(store.path), "--approval-id", aid], clock=store.clock)
    assert store.pending() == [] and store.live_for("sha256:x", "sha256:b") is None


def test_row_written_without_a_valid_hmac_is_refused(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    _approve(store, aid)
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE approvals SET status='approved', token='00'*32, consumed_at=NULL")
        conn.execute("INSERT INTO approvals (approval_id, step_digest, plan_digest, before_digest, rendering, "
                     "created_at, expires_at, status, token, nonce) VALUES ('ap_forged','sha256:z','sha256:p',"
                     "'sha256:b','{}',?,?,'approved','ab','cd')", (T0.isoformat(), (T0 + timedelta(hours=1)).isoformat()))
    assert store.live_for("sha256:x", "sha256:b") is None
    assert store.live_for("sha256:z", "sha256:b") is None


def test_no_key_file_means_nothing_verifies(store, tmp_path):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    _approve(store, aid)
    os.remove(store.key_path)
    assert store.live_for("sha256:x", "sha256:b") is None


def test_approve_cli_refuses_without_a_console(store):
    aid = store.request("sha256:x", "sha256:p", "sha256:b", RENDER)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    kwargs = {"creationflags": subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.run(
        [sys.executable, "-m", "accountable_surface.authority_cli", "approve", "--state", str(store.path),
         "--approval-id", aid], input="submit\n127.0.0.1:8765\n", capture_output=True, text=True,
        env=env, timeout=60, **kwargs)
    assert proc.returncode != 0
    assert "console" in json.loads(proc.stdout.strip().splitlines()[-1])["reason"]
    assert store.live_for("sha256:x", "sha256:b") is None and len(store.pending()) == 1


def test_pause_persists_across_a_restart_and_only_the_cli_clears_it(tmp_path):
    first = ApprovalStore(tmp_path / "a.db", clock=Clock())
    first.pause("http://127.0.0.1:8765", "R3.challenge", "sha256:ev")
    second = ApprovalStore(tmp_path / "a.db", clock=Clock())
    assert second.paused_targets() == frozenset({"http://127.0.0.1:8765"})
    authority_cli.main(["clear-pause", "--state", str(second.path), "--target", "http://127.0.0.1:8765",
                        "--reason", "handled the check by hand"], clock=second.clock)
    assert second.paused_targets() == frozenset()
    assert [e["action"] for e in second.pause_log()] == ["pause", "clear"]


def test_only_the_operator_cli_calls_approve_or_clear_pause():
    callers = set()
    for path in (SRC / "accountable_surface").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in ("approve", "clear_pause", "deny"):
                callers.add(path.name)
    assert callers <= {"authority_cli.py", "approvals.py"}
