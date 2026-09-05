"""Which effectors a remote caller can reach at all -- the operator's decision,
taken before any grant is consulted.

Exposing `actuate` over MCP puts real actuation on a surface a model calls. The
registry is what makes that safe to turn on one `action_kind` at a time. It is
EMPTY unless the operator names a spec file, so a fresh install exposes nothing,
and an action kind the file does not carry cannot be actuated no matter what a
grant says.

Two operator decisions, and both have to agree:

  registry   what a caller can reach at all. A capability the file does not name
             does not exist for that caller.
  grant      what may be done with it, checked by proof-surface's gate at the
             moment of the call.

The registry never widens a grant, and a grant never widens the registry. An
exposed effector with no matching grant still denies.

The spec file (`ACCOUNTABLE_SURFACE_EFFECTORS`) is a JSON object:

  {"effectors": [
     {"action_kind": "fs.write", "type": "filesystem", "root": "/srv/agent-sandbox"},
     {"action_kind": "api.post", "type": "api", "service": "github"}
  ]}

Deliberate null: `command`, `browser`, and `web` are NOT constructible here. Each
reaches past a bounded file root or one declared API operation, and none of them
has been through a review for a caller the operator cannot see. A spec naming one
is refused BY NAME and the refusal is reported by `doctor`, so a capability never
appears or disappears silently.

Fail-closed is not enough on its own: a registry that emptied itself on a typo
would read exactly like an operator who exposed nothing on purpose. Every reason
the set came out smaller than the file is kept and reported.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from accountable_surface.api_effector import GITHUB_ISSUE_COMMENTS, ApiCall, ApiEffector, ApiService
from accountable_surface.effector import FilesystemEffector

ENV_VAR = "ACCOUNTABLE_SURFACE_EFFECTORS"

SERVICES: dict[str, ApiService] = {"github": GITHUB_ISSUE_COMMENTS}

NOT_EXPOSED = {
    "command": "it runs a program on the operator's machine",
    "browser": "it drives a real browser session, carrying the operator's cookies",
    "web": "it posts to an origin the caller names",
}


class SpecError(ValueError):
    """An entry in the operator's spec file that this module will not build."""


class ContentError(ValueError):
    """Content a caller handed in that the exposed effector cannot read."""


@dataclass(frozen=True)
class Exposed:
    """One action kind a caller may ask for: the effector behind it, how to read
    the caller's content, and a one-line rendering of its reach for `doctor`."""

    action_kind: str
    effector: Any
    decode: Callable[[str], Any]
    describe: str


class EffectorRegistry:
    """The exposed set, alongside every entry that was refused and why."""

    def __init__(self, exposed: dict[str, Exposed], refusals: list[str]) -> None:
        self._exposed = dict(exposed)
        self._refusals = list(refusals)

    def __len__(self) -> int:
        return len(self._exposed)

    def get(self, action_kind: str) -> Exposed | None:
        return self._exposed.get(action_kind)

    def action_kinds(self) -> list[str]:
        return sorted(self._exposed)

    def refusals(self) -> list[str]:
        return list(self._refusals)

    def describe(self) -> dict:
        """What `doctor` reports: the reach of each exposed effector, and the
        refusals, so an operator can see a typo instead of guessing at silence."""
        return {
            "exposed": [
                {"action_kind": kind, "bound": self._exposed[kind].describe}
                for kind in self.action_kinds()
            ],
            "refused": self.refusals(),
        }


# --- reading what the caller handed in --------------------------------------


def _decode_bytes(content: str) -> bytes:
    return content.encode("utf-8")


def _decode_api_call(content: str) -> ApiCall:
    """The caller hands in an intent and a body, and nothing else. A header, a
    host, or a token has nowhere to land in that shape."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise ContentError(f"api content must be a JSON object ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("intent"), str):
        raise ContentError('api content must be {"intent": "<name>", "body": {...}}')
    body = data.get("body", {})
    if not isinstance(body, dict):
        raise ContentError("api content 'body' must be an object")
    return ApiCall(data["intent"], body)


# --- building one entry ------------------------------------------------------


def _build_filesystem(entry: dict, api_driver: Any) -> tuple[Any, Callable, str, set[str]]:
    root = entry.get("root")
    if not isinstance(root, str) or not root:
        raise SpecError("a filesystem entry needs a non-empty 'root'")
    describe = f"filesystem root={Path(root).resolve().as_posix()}"
    return FilesystemEffector(root), _decode_bytes, describe, {FilesystemEffector.action_kind}


def _build_api(entry: dict, api_driver: Any) -> tuple[Any, Callable, str, set[str]]:
    name = entry.get("service")
    service = SERVICES.get(name) if isinstance(name, str) else None
    if service is None:
        raise SpecError(f"unknown api service {name!r}; known services: {sorted(SERVICES)}")
    if api_driver is None:
        from accountable_surface.api_transport import UrllibApiDriver

        api_driver = UrllibApiDriver()
    intents = sorted(op.intent for op in service.operations)
    describe = f"api service={service.name} origin={service.origin} intents={intents}"
    kinds = {op.action_kind for op in service.operations}
    return ApiEffector(api_driver, service), _decode_api_call, describe, kinds


BUILDERS: dict[str, Callable[[dict, Any], tuple]] = {
    "filesystem": _build_filesystem,
    "api": _build_api,
}


def _build_one(type_name: Any, entry: dict, api_driver: Any) -> tuple:
    if type_name in NOT_EXPOSED:
        raise SpecError(
            f"type {type_name!r} is deliberately not exposed over MCP: {NOT_EXPOSED[type_name]}"
        )
    builder = BUILDERS.get(type_name) if isinstance(type_name, str) else None
    if builder is None:
        raise SpecError(f"unknown type {type_name!r}; exposable types: {sorted(BUILDERS)}")
    return builder(entry, api_driver)


def _build(entries: list, api_driver: Any) -> EffectorRegistry:
    exposed: dict[str, Exposed] = {}
    refusals: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            refusals.append(f"entry {index}: not an object")
            continue
        kind, type_name = entry.get("action_kind"), entry.get("type")
        try:
            effector, decode, describe, kinds = _build_one(type_name, entry, api_driver)
        except SpecError as exc:
            refusals.append(f"entry {index} (type {type_name!r}): {exc}")
            continue
        if not isinstance(kind, str) or kind not in kinds:
            refusals.append(
                f"entry {index}: action_kind {kind!r} is not one this effector serves {sorted(kinds)}"
            )
            continue
        if kind in exposed:
            refusals.append(f"entry {index}: action_kind {kind!r} is already exposed; the first entry stands")
            continue
        exposed[kind] = Exposed(kind, effector, decode, describe)
    return EffectorRegistry(exposed, refusals)


def load_effectors(path_str: str | None = None, *, api_driver: Any = None) -> EffectorRegistry:
    """Load the operator's exposure spec. Nothing named, nothing readable, or
    nothing well-formed all come back as an EMPTY registry carrying the reason.

    `api_driver` is the injection point that keeps this testable with no network
    and no credential; left None, an api entry gets the stdlib transport.
    """
    path_str = path_str or os.environ.get(ENV_VAR)
    if not path_str:
        return EffectorRegistry({}, [f"no {ENV_VAR} file is named -- nothing is exposed"])
    try:
        data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return EffectorRegistry({}, [f"{ENV_VAR} file is unreadable ({type(exc).__name__}) -- nothing is exposed"])
    entries = data.get("effectors") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return EffectorRegistry({}, [f"{ENV_VAR} file carries no 'effectors' list -- nothing is exposed"])
    return _build(entries, api_driver)
