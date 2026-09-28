"""Operator-side durable authority commands.

This module is a local CLI surface, not an MCP tool. It records durable grant
revocations and recovery decisions without returning grant bodies, and it is the
only place an actuation approval is granted or a paused target is cleared.
`approve` re-renders the step from the stored record and asks the person to type
the action verb and the target host at an interactive console (CONIN$ on
Windows, /dev/tty elsewhere). With no console it refuses, so piped input cannot
approve anything.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from accountable_surface.approvals import ApprovalStore, utc_now
from accountable_surface.authority_state import DurableAuthorityState, grant_ref

APPROVAL_COMMANDS = ("list-pending", "approve", "deny", "clear-pause")


def main(argv: list[str] | None = None, *, console: Any = None, clock: Any = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command in APPROVAL_COMMANDS:
            payload = _approval_dispatch(args, ApprovalStore(args.state, clock=clock or utc_now), console)
        else:
            payload = _dispatch(args)
    except Exception as exc:
        payload = {"ok": False, "reason": str(exc)}
        print(json.dumps(payload, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(payload, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="accountable-surface-authority")
    sub = parser.add_subparsers(dest="command", required=True)
    revoke = sub.add_parser("revoke")
    _state_arg(revoke)
    revoke.add_argument("--grant", required=True)
    revoke.add_argument("--reason", required=True)
    release = sub.add_parser("recover-precommit")
    _state_arg(release)
    _reservation_args(release)
    ambiguous = sub.add_parser("mark-ambiguous")
    _state_arg(ambiguous)
    _reservation_args(ambiguous)
    doctor = sub.add_parser("doctor")
    _state_arg(doctor)
    _approval_parsers(sub)
    return parser


def _approval_parsers(sub) -> None:
    _state_arg(sub.add_parser("list-pending"))
    for name in ("approve", "deny"):
        cmd = sub.add_parser(name)
        _state_arg(cmd)
        cmd.add_argument("--approval-id", required=True)
        cmd.add_argument("--approver", default=None)
    clear = sub.add_parser("clear-pause")
    _state_arg(clear)
    clear.add_argument("--target", required=True)
    clear.add_argument("--reason", required=True)


def _state_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True)


def _reservation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reservation-id", required=True)
    parser.add_argument("--reason", required=True)


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    state = DurableAuthorityState(args.state)
    if args.command == "revoke":
        grant = _load_grant(args.grant)
        digest = state.record_revocation(grant, args.reason)
        return {"ok": True, "status": "revoked", "grant_ref": grant_ref(grant), "reason_digest": digest}
    if args.command == "recover-precommit":
        state.release_precommit(args.reservation_id, args.reason)
        return {"ok": True, "status": "released_precommit", "reservation_id": args.reservation_id}
    if args.command == "mark-ambiguous":
        state.mark_ambiguous(args.reservation_id, args.reason)
        return {"ok": True, "status": "ambiguous", "reservation_id": args.reservation_id}
    if args.command == "doctor":
        return {"ok": True, "status": "authority-state", "recovery": state.recovery_report()}
    raise SystemExit("unknown command")


class TtyConsole:
    """The person's own console, opened directly so a pipe cannot stand in for it."""

    def __init__(self) -> None:
        if os.name == "nt":
            self._in = open("CONIN$", encoding="utf-8")  # noqa: SIM115 - held for the prompt
            self._out = open("CONOUT$", "w", encoding="utf-8")  # noqa: SIM115
        else:
            self._in = self._out = open("/dev/tty", "r+", encoding="utf-8")  # noqa: SIM115

    def show(self, text: str) -> None:
        self._out.write(text + chr(10))
        self._out.flush()

    def ask(self, prompt: str) -> str:
        self._out.write(prompt)
        self._out.flush()
        return self._in.readline().strip()


def _open_console():
    try:
        return TtyConsole()
    except OSError as exc:
        raise RuntimeError("approve needs an interactive console; it refuses piped or detached input") from exc


def _approve(store: ApprovalStore, args: argparse.Namespace, console: Any) -> dict[str, Any]:
    record = store.get(args.approval_id)
    if record is None or record["status"] != "pending":
        raise ValueError("no pending approval with that id")
    console = console or _open_console()
    rendering = record["rendering"]
    verb = str(rendering.get("action_kind", "")).rsplit(".", 1)[-1].lower()
    host = urlsplit(str((rendering.get("target") or {}).get("origin", ""))).netloc.lower()
    console.show(json.dumps(rendering, indent=2, sort_keys=True))
    typed_verb = console.ask("Type the action verb shown above to approve it: ").lower()
    typed_host = console.ask("Type the target host shown above: ").lower()
    if typed_verb != verb or typed_host != host:
        raise ValueError("the answers do not match the stored step; nothing was approved")
    approved = store.approve(args.approval_id, approver=args.approver or getpass.getuser())
    return {"ok": True, "status": "approved", "approval_id": approved["approval_id"],
            "expires_at": approved["expires_at"]}


def _approval_dispatch(args: argparse.Namespace, store: ApprovalStore, console: Any) -> dict[str, Any]:
    if args.command == "list-pending":
        return {"ok": True, "pending": store.pending()}
    if args.command == "approve":
        return _approve(store, args, console)
    if args.command == "deny":
        store.deny(args.approval_id, approver=args.approver or getpass.getuser())
        return {"ok": True, "status": "denied", "approval_id": args.approval_id}
    cleared = store.clear_pause(args.target, by=getpass.getuser(), reason=args.reason)
    return {"ok": cleared, "status": "cleared" if cleared else "not-paused", "target": args.target}


def _load_grant(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("grant file must contain one grant object")
    return data


if __name__ == "__main__":
    main()
