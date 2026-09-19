"""Operator-side durable authority recovery commands.

This module is a local CLI surface, not an MCP tool. It records durable grant
revocations and recovery decisions without returning grant bodies.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from accountable_surface.authority_state import DurableAuthorityState, grant_ref


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
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
    return parser


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


def _load_grant(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("grant file must contain one grant object")
    return data


if __name__ == "__main__":
    main()
