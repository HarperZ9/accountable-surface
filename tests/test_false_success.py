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
  ApiEffector         a 201 Created for a member the service never stored. Only a
                      re-read of the collection tells the difference.
  UiaEffector         an invoke the window reported and did nothing with, and an
                      absence read off a tree that was clipped before the control.
  Escalator           a rung-3 sight whose provenance is fully formed, read as
                      though the structural question had been answered.

`UiaEffector` is the one rung whose caller declares the post-condition, so its
control asserts the declared condition is checked against a fresh read of the window
rather than against the instrument's own `ok`.

Open nulls, stated rather than tested green. `CommandEffector.verify` reads the
runner's exit code, so a command that exits 0 without doing its work still passes.
`BrowserEffector.verify` for a click compares page digests, so a page carrying a
nonce would make every click look effective. `web.submit` checks the response page
the service returned, which is closer to the resource than the request's status but
is still the service's own account rather than an independent re-read of what it
stored. Moving those three onto a declared post-condition is open work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from coherence_membrane.observation import Observation, Provenance, Status
from coherence_membrane.pngencode import encode_png

from accountable_surface.api_effector import (
    GITHUB_ISSUE_COMMENTS,
    ApiCall,
    ApiEffector,
    FakeApiDriver,
)
from accountable_surface.browser_effector import BrowserAction, BrowserEffector, FakeBrowserDriver
from accountable_surface.effector import FilesystemEffector
from accountable_surface.escalator import Question, structure_ladder
from accountable_surface.os_effector import CommandEffector
from accountable_surface.surface import AccountableSurface
from accountable_surface.uia import SCHEME, FakeUiaDriver, FakeWindow, UiaStructureOrgan
from accountable_surface.uia_effector import UiaCommand, UiaEffector
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


# --- ApiEffector: 201 Created for a member the service never stored ----------


class _EchoingApiDriver(FakeApiDriver):
    """Answers 201 with the created member, id and all, and stores nothing. This is
    the shape of a write that a permissive backend accepts and then discards, and a
    verify that read the response instead of the resource would call it a success."""

    def request(self, method, url, headers, body):
        if method != "POST":
            return super().request(method, url, headers, body)
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        member = dict(json.loads(body or b"{}"))
        member["id"] = 1
        return {"status": 201, "body": json.dumps(member, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8")}


def test_a_201_for_a_member_the_service_never_stored_does_not_verify(monkeypatch):
    monkeypatch.setenv(GITHUB_ISSUE_COMMENTS.auth_env, "fake-token-for-tests-only")
    thread = "/repos/octo/demo/issues/7/comments"
    driver = _EchoingApiDriver({thread: []})
    out = AccountableSurface().actuate(ApiEffector(driver, GITHUB_ISSUE_COMMENTS), target=thread,
                                       content=ApiCall("post_comment", {"body": "hello"}),
                                       authorization=_grant(["api.post"]))
    assert out.acted is True           # the request left and came back 201
    assert out.verified is False       # the collection does not carry it
    assert out.certificate["verdict"] == "refuted"
    assert driver._collections[thread] == []


# --- UiaEffector: dispatched to the window, and nothing happened -------------


def _dialog_window():
    return FakeWindow(elements=[{"name": "Save", "type": "Button"},
                                {"name": "Field", "type": "Edit"},
                                {"name": "Dialog", "type": "Window"}])


def test_an_invoke_the_window_ignored_does_not_verify():
    """`uia.ps1` answers `ok` for an invoke it dispatched, whatever the application
    did with it. A disabled control, a modal that swallowed the click, and a handler
    that threw all look identical from there, so the verdict has to come from the
    window."""
    driver = FakeUiaDriver({"Notepad": _dialog_window()})   # no effect declared
    out = AccountableSurface().actuate(
        UiaEffector(driver, "Notepad"), target=f"{SCHEME}Notepad/Save",
        content=UiaCommand("invoke", expect={"kind": "appears", "element": "Saved"}),
        authorization=_grant(["uia.invoke"]), allow_irreversible=True)
    assert out.acted is True
    assert [r["verb"] for r in driver.requests].count("invoke") == 1
    assert out.verified is False
    assert out.certificate["verdict"] == "refuted"
    assert "did not land" in " ".join(out.reasons)


def test_an_absence_read_off_a_truncated_tree_does_not_verify():
    """The one post-condition a partial view would read as success. `Dialog` sits past
    the cut, so a check that only asked whether the control was in the elements it got
    back would call an unclosed dialog closed."""
    driver = FakeUiaDriver({"Notepad": _dialog_window()}, truncate_at=2)
    out = AccountableSurface().actuate(
        UiaEffector(driver, "Notepad"), target=f"{SCHEME}Notepad/Save",
        content=UiaCommand("invoke", expect={"kind": "disappears", "element": "Dialog"}),
        authorization=_grant(["uia.invoke"]), allow_irreversible=True)
    assert out.acted is True
    assert "Dialog" not in [e["name"] for e in driver.windows["Notepad"].elements[:2]]
    assert any(e["name"] == "Dialog" for e in driver.windows["Notepad"].elements)
    assert out.verified is False
    assert "truncated" in " ".join(out.reasons)


def test_an_absence_read_off_a_tree_with_nothing_named_does_not_verify():
    """The same false success with nothing to notice. Invoking `Close` empties this
    window, so the tree comes back whole, uncut, and carrying no names. That answer is
    identical to one from a window that refused to open its tree, and a check that
    only asked whether `Dialog` was in the elements it got back would read it as a
    dialog that closed."""
    window = _dialog_window()
    window.elements.append({"name": "Close", "type": "Button"})
    window.effects = {"Close": {"remove": ["Save", "Field", "Dialog", "Close"]}}
    driver = FakeUiaDriver({"Notepad": window})
    out = AccountableSurface().actuate(
        UiaEffector(driver, "Notepad"), target=f"{SCHEME}Notepad/Close",
        content=UiaCommand("invoke", expect={"kind": "disappears", "element": "Dialog"}),
        authorization=_grant(["uia.invoke"]), allow_irreversible=True)
    assert out.acted is True
    assert driver.windows["Notepad"].elements == []   # the read is not partial
    assert out.verified is False
    assert out.certificate["verdict"] == "refuted"
    assert "nothing named" in " ".join(out.reasons)


def test_a_label_two_controls_carry_does_not_verify_as_gone():
    """Refusing a duplicate label is what creates this one. A resolution that answers
    `ambiguous` reads as not-found to any caller checking for a match, and a
    disappearance check would then call the dialog closed with two of them on screen.
    Ambiguity has to be its own outcome rather than a failure to resolve."""
    window = _dialog_window()
    window.elements.append({"name": "Dialog", "type": "Window", "automationId": "dlg-2"})
    driver = FakeUiaDriver({"Notepad": window})
    out = AccountableSurface().actuate(
        UiaEffector(driver, "Notepad"), target=f"{SCHEME}Notepad/Save",
        content=UiaCommand("invoke", expect={"kind": "disappears", "element": "Dialog"}),
        authorization=_grant(["uia.invoke"]), allow_irreversible=True)
    assert out.acted is True
    assert len([e for e in driver.windows["Notepad"].elements
                if e["name"] == "Dialog"]) == 2   # both still on screen
    assert out.verified is False
    assert out.certificate["verdict"] == "refuted"
    assert "more than one control" in " ".join(out.reasons)


# --- Escalator: a strong receipt for a question nobody answered --------------


def test_a_witnessed_sight_is_not_an_answer_to_a_structural_question():
    """The ladder's false success. When rung 0 cannot settle a label, rung 3 comes
    back with a real perception: a content digest, a perceptual hash, a coarse
    description that reads like confidence. A caller checking whether an Observation
    with provenance came back would accept it. None of that resolves a control name,
    so the ascent has to stay unanswered while still handing the sight over."""
    driver = FakeUiaDriver({"Notepad": _dialog_window()}, truncate_at=2)
    png = encode_png(8, 8, bytes([180, 180, 180] * 64), channels=3)
    ascent = structure_ladder(UiaStructureOrgan(driver), "Notepad",
                              lambda: png).resolve(Question("present", "Dialog"))
    sight = ascent.witness
    assert sight is not None and sight.organ == "pixel-sight"
    assert sight.provenance.digest.startswith("sha256:")   # a full, honest receipt
    assert len(sight.data["phash"]) == 16
    assert sight.status is Status.NEEDS_HUMAN               # and it settles nothing
    assert ascent.answer is None
    assert ascent.rederivable == "none"
    assert all(a.outcome == "fell" for a in ascent.attempts)
