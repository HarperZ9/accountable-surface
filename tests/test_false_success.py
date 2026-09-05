"""False-success controls -- one per shipped effector.

A gate that only ever sees correct inputs proves nothing. For each effector the
question is how a passing verify could accept a wrong result, and each case below
deliberately produces that situation and asserts the verdict is not a pass.

What each control puts pressure on:

  FilesystemEffector  the actor reports success it did not achieve. The surface
                      must re-perceive independently instead of believing it.
  CommandEffector     stale self-report. A runner that dies must not leave the
                      previous command's exit code standing as this one's result.
  WebEffector         the service accepts the request and silently drops the write
                      (the 200-that-did-nothing). Verify has to read the resource.
  BrowserEffector     an action that dispatched cleanly and changed nothing.

Open nulls, stated rather than tested green. `CommandEffector.verify` reads the
runner's exit code, so a command that exits 0 without doing its work still passes.
`BrowserEffector.verify` for a click compares page digests, so a page carrying a
nonce would make every click look effective. `web.submit` checks the response page
the service returned, which is closer to the resource than the request's status but
is still the service's own account rather than an independent re-read of what it
stored. Each of those wants a caller-supplied post-condition, which the effector
contract does not take yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from coherence_membrane.observation import Observation, Provenance, Status

from accountable_surface.browser_effector import BrowserAction, BrowserEffector, FakeBrowserDriver
from accountable_surface.effector import FilesystemEffector
from accountable_surface.os_effector import CommandEffector
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import FakePageDriver, WebAction, WebEffector


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-false-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "false-success-agent"},
        "intent": "false-success control",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


# --- FilesystemEffector: the actor claims a write it never made -------------


class _LyingEffector(FilesystemEffector):
    """Writes nothing, then hands back a witnessed-looking Observation whose digest
    says the intended content is on disk. Anything that trusts the actor's return
    value accepts a file that does not exist."""

    def act(self, plan, allow_receipt, content):
        self._backups[plan.target] = None  # stay rollback-safe; the lie is the report
        return Observation(
            organ=self.name,
            subject=f"file://{plan.target}",
            summary=f"file present ({len(content)} bytes)",
            status=Status.PASS,
            provenance=Provenance.witness_bytes(f"file://{plan.target}", content, "high"),
            data={"exists": True, "size": len(content), "sha256": plan.content_sha256},
        )


def test_a_fabricated_success_report_does_not_verify(tmp_path):
    target = str(tmp_path / "f.txt")
    out = AccountableSurface().actuate(_LyingEffector(tmp_path), target=target, content=b"hello",
                                       authorization=_grant(["fs.write"]))
    assert out.acted is True          # the surface believes it ran the effector
    assert out.verified is False      # its own re-perception says otherwise
    assert out.certificate["verdict"] == "refuted"
    assert not Path(target).exists()


# --- CommandEffector: a dead runner must not inherit the last success -------


class _FlakyRunner:
    def __init__(self):
        self.raise_next = False

    def run(self, argv, cwd):
        if self.raise_next:
            raise RuntimeError("runner died")
        return {"exit_code": 0, "stdout": "", "stderr": ""}


def test_a_dead_runner_does_not_report_the_previous_command_as_this_one(tmp_path):
    runner = _FlakyRunner()
    effector = CommandEffector(runner, {"echo"}, tmp_path)
    surface = AccountableSurface()
    first = surface.actuate(effector, target="probe-1", content=["echo", "hi"],
                            authorization=_grant(["os.run"]), allow_irreversible=True)
    assert first.verified is True

    runner.raise_next = True
    with pytest.raises(RuntimeError):
        surface.actuate(effector, target="probe-2", content=["echo", "hi"],
                        authorization=_grant(["os.run"]), allow_irreversible=True)

    after = effector.perceive("probe-2")
    assert after.data["last_exit"] is None   # NOT the 0 from probe-1
    plan = effector.preview("probe-2", ["echo", "hi"])
    assert effector.verify(plan, after).status == "failed"


# --- WebEffector: accepted, and silently dropped ----------------------------


class _DroppingDriver(FakePageDriver):
    """Accepts every write and keeps none of it -- the shape of a service that
    answers 200 and drops the body."""

    def fill(self, selector, value):
        return None

    def submit(self, url, data):
        self.navigate(url)
        self._pages[url]["title"] = "Error"


def test_a_dropped_field_write_does_not_verify():
    driver = _DroppingDriver(start="https://ok.test/form")
    effector = WebEffector(driver, allowed_origins=["https://ok.test"])
    action = WebAction("fill", url="https://ok.test/form", selector="email", value="a@b.test")
    out = AccountableSurface().actuate(effector, target="https://ok.test/form", content=action,
                                       authorization=_grant(["web.fill"]))
    assert out.acted is True
    assert out.verified is False
    assert driver.field_value("email") is None


def test_a_submit_that_lands_but_drops_the_write_does_not_verify():
    driver = _DroppingDriver(start="https://ok.test/form")
    effector = WebEffector(driver, allowed_origins=["https://ok.test"])
    # value carries the intended post-condition: the title the response must have.
    action = WebAction("submit", url="https://ok.test/saved", value="Saved")
    out = AccountableSurface().actuate(effector, target="https://ok.test/saved", content=action,
                                       authorization=_grant(["web.submit"]), allow_irreversible=True)
    assert out.acted is True
    assert driver.current_url() == "https://ok.test/saved"   # the request "succeeded"
    assert out.verified is False                              # the resource says it did not


# --- BrowserEffector: dispatched cleanly, changed nothing -------------------


def test_an_inert_click_does_not_verify():
    driver = FakeBrowserDriver({"https://ok.test/app": {"title": "App", "fields": {}}},
                               start="https://ok.test/app")
    effector = BrowserEffector(driver, allowed_origins=["https://ok.test"])
    action = BrowserAction("click", url="https://ok.test/app", selector="Save")
    out = AccountableSurface().actuate(effector, target="https://ok.test/app", content=action,
                                       authorization=_grant(["browser.click"]))
    assert out.acted is True
    assert out.verified is False
    assert "NO effect" in " ".join(out.reasons)


def test_a_script_that_returns_nothing_does_not_verify():
    driver = FakeBrowserDriver({"https://ok.test/app": {"title": "App", "fields": {}}},
                               start="https://ok.test/app")
    effector = BrowserEffector(driver, allowed_origins=["https://ok.test"])
    action = BrowserAction("evaluate", url="https://ok.test/app", value="doSomething()")
    out = AccountableSurface().actuate(effector, target="https://ok.test/app", content=action,
                                       authorization=_grant(["browser.evaluate"]),
                                       allow_irreversible=True)
    assert out.acted is True
    assert out.verified is False
