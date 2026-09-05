"""Rung 0 of the escalation ladder: the structural surface of a Windows window.

A window's controls carry accessible names, roles, and AutomationIds. Reading them
is cheap, and a second party with the same window can run the same query and compare
the answer, which is what makes a structural observation witnessable at all. A
screenshot is not, so the ladder starts here and reaches for pixels last.

`uia.ps1` (telos) is the instrument. It speaks JSON both ways and always exits 0, so
a refusal arrives as data rather than as a crash. This module holds the driver
contract, an in-memory driver that makes the whole path testable with no window and
no Windows, and the rung-0 organ. The PowerShell-backed driver lives in
`uia_transport.py`, deliberately apart, the way `api_transport.py` sits apart from
`api_effector.py`.

The driver contract is one method:

    run(verb: str, args: list[str]) -> dict

carrying a verb and the positional arguments `uia.ps1` declares (`tree <window>
[max]`, `value <window> <element>`, `invoke <window> <element>`, `setvalue <window>
<element> <text>`) and returning that script's parsed answer. Every answer carries
`ok`; a failure carries `error`.

Two limits of a structural read, both kept rather than rounded up:

  * A TRUNCATED tree is a partial view. An element that exists can read as absent, so
    the observation's status is UNVERIFIED and any check resting on absence has to
    refuse instead of passing.
  * Exact-name resolution takes the first match. `uia.ps1` reports ambiguity only for
    a substring match, so two controls sharing an accessible name resolve to whichever
    the tree walk reached first, silently. An AutomationId is the way past that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex

SCHEME = "uia://"


def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def element_facts(raw: Any) -> dict:
    """The three structural facts and nothing else, so what gets witnessed is what
    another party can re-derive from the same window."""
    data = raw if isinstance(raw, dict) else {}
    return {
        "name": str(data.get("name") or ""),
        "type": str(data.get("type") or ""),
        "automationId": str(data.get("automationId") or ""),
    }


def match_element(elements: list, needle: str) -> dict:
    """The resolution ladder `uia.ps1` uses, mirrored so a plan resolves the same way
    offline as it does against a live window: exact name, then exact AutomationId, then
    a UNIQUE substring of a name. Every comparison ignores case, because PowerShell's
    `-eq` on strings does.

    Returns `{"status": "ok", "index": .., "how": ..}` or a refusal carrying `status`
    "ambiguous", "none", or "invalid".
    """
    if not needle:
        return {"status": "invalid", "reason": "empty match"}
    folded = needle.lower()
    for index, element in enumerate(elements):
        if str(element.get("name") or "").lower() == folded:
            return {"status": "ok", "index": index, "how": "name-exact"}
    for index, element in enumerate(elements):
        ident = str(element.get("automationId") or "")
        if ident and ident.lower() == folded:
            return {"status": "ok", "index": index, "how": "automationid-exact"}
    hits = [i for i, e in enumerate(elements) if folded in str(e.get("name") or "").lower()]
    if len(hits) == 1:
        return {"status": "ok", "index": hits[0], "how": "name-substring-unique"}
    if hits:
        return {"status": "ambiguous", "how": "name-substring",
                "candidates": [elements[i].get("name") for i in hits[:10]]}
    return {"status": "none"}


@dataclass
class FakeWindow:
    """One window's controls for the in-memory driver: what is in the tree, what each
    control's value is, what invoking one changes, and which controls answer to
    neither pattern."""

    elements: list = field(default_factory=list)
    values: dict = field(default_factory=dict)  # control name -> current value
    effects: dict = field(default_factory=dict)  # control name -> what invoking it changes
    no_invoke: set = field(default_factory=set)
    no_value: set = field(default_factory=set)


class FakeUiaDriver:
    """A deterministic window tree answering in the shapes `uia.ps1` answers in.

    The default behaviour of `invoke` is the interesting one: it reports `ok` and
    changes NOTHING unless the window declares an effect for that control. That is
    precisely the false success a verify would accept if it read the instrument's own
    account of its work instead of re-reading the window.

    `requests` records every call, so a test can assert what did and did not travel.
    """

    def __init__(self, windows: dict, *, truncate_at: int | None = None) -> None:
        self.windows = windows
        self.requests: list = []
        self._truncate_at = truncate_at

    def run(self, verb: str, args: list) -> dict:
        self.requests.append({"verb": verb, "args": list(args)})
        table = {"tree": self._tree, "value": self._value,
                 "invoke": self._invoke, "setvalue": self._setvalue}
        handler = table.get(verb)
        if handler is None:
            return {"ok": False, "error": f"unknown verb: {verb}"}
        title = args[0] if args else ""
        window = self.windows.get(title)
        if window is None:
            return {"ok": False, "error": f"no window matched: {title}"}
        return handler(title, window, list(args[1:]))

    # --- the four verbs ------------------------------------------------------

    def _tree(self, title: str, window: FakeWindow, rest: list) -> dict:
        elements = [element_facts(e) for e in window.elements]
        limit = self._truncate_at
        shown = elements if limit is None else elements[:limit]
        return {"ok": True, "window": title, "count": len(shown),
                "descendants": len(elements), "max": limit,
                "truncated": limit is not None and len(elements) > limit,
                "elements": shown}

    def _value(self, title: str, window: FakeWindow, rest: list) -> dict:
        chosen = match_element(window.elements, rest[0] if rest else "")
        if chosen["status"] != "ok":
            return _deny(chosen)
        element = window.elements[chosen["index"]]
        name = str(element.get("name") or "")
        if name in window.no_value:
            return {"ok": False, "error": f"element has no ValuePattern: {name}"}
        return {"ok": True, "name": name, "matched": chosen["how"],
                "type": element.get("type"), "value": window.values.get(name)}

    def _invoke(self, title: str, window: FakeWindow, rest: list) -> dict:
        chosen = match_element(window.elements, rest[0] if rest else "")
        if chosen["status"] != "ok":
            return _deny(chosen)
        name = str(window.elements[chosen["index"]].get("name") or "")
        if name in window.no_invoke:
            return {"ok": False, "error": f"element has no InvokePattern: {name}"}
        _apply(window, window.effects.get(name, {}))
        return {"ok": True, "invoked": name, "matched": chosen["how"]}

    def _setvalue(self, title: str, window: FakeWindow, rest: list) -> dict:
        chosen = match_element(window.elements, rest[0] if rest else "")
        if chosen["status"] != "ok":
            return _deny(chosen)
        name = str(window.elements[chosen["index"]].get("name") or "")
        if name in window.no_value:
            return {"ok": False, "error": f"element has no ValuePattern: {name}"}
        window.values[name] = rest[1] if len(rest) > 1 else ""
        return {"ok": True, "name": name, "matched": chosen["how"]}


def _deny(chosen: dict) -> dict:
    """A refusal in the shape `uia.ps1` refuses in: never a match, always a reason."""
    return {"ok": False, "error": f"element {chosen['status']}",
            "matched": chosen.get("how"), "candidates": chosen.get("candidates", []),
            "hint": "name the control exactly, or use its AutomationId"}


def _apply(window: FakeWindow, effect: dict) -> None:
    for name in effect.get("remove", []):
        window.elements = [e for e in window.elements if str(e.get("name") or "") != name]
    window.elements.extend(dict(e) for e in effect.get("add", []))
    window.values.update(effect.get("set", {}))


class UiaStructureOrgan:
    """Rung 0: a witnessed read of one window's control tree.

    The cheapest rung, and the only one whose answer another party can re-derive by
    name and role. The provenance carries the command that produced it, so re-deriving
    it does not depend on this process being around.
    """

    name = "uia-structure"

    def __init__(self, driver: Any, max_elements: int = 400) -> None:
        self._driver = driver
        self._max = max_elements

    def observe(self, window: str) -> Observation:
        answer = self._driver.run("tree", [window, str(self._max)])
        elements = [element_facts(e) for e in (answer.get("elements") or [])]
        truncated = bool(answer.get("truncated"))
        settled = bool(answer.get("ok")) and not truncated
        if answer.get("ok"):
            summary = f"{window}: {len(elements)} controls"
            if truncated:
                summary += " (TRUNCATED -- absence is not established)"
        else:
            summary = f"{window}: {answer.get('error') or 'unreadable'}"
        return Observation(
            organ=self.name,
            subject=f"{SCHEME}{window}",
            summary=summary,
            # A partial tree is a partial view: a control that exists can read as
            # absent, so nothing about absence is settled by one.
            status=Status.PASS if settled else Status.UNVERIFIED,
            provenance=Provenance.witness_bytes(
                f"{SCHEME}{window}", canon(elements), "high" if settled else "moderate",
                command=f"uia.ps1 tree {window} {self._max}",
            ),
            data={"window": window, "ok": bool(answer.get("ok")), "elements": elements,
                  "truncated": truncated, "descendants": answer.get("descendants"),
                  "sha256": sha256_hex(canon(elements))},
        )

    def selftest(self) -> bool:
        """Falsifiable: a partial tree must not come back as a settled read.

        Probes `type(self)` rather than this class by name, so an organ that wraps or
        replaces the read cannot inherit a green selftest for behaviour it does not
        have."""
        window = FakeWindow(elements=[{"name": f"control-{i}"} for i in range(3)])
        probe = type(self)
        full = probe(FakeUiaDriver({"probe": window})).observe("probe")
        clipped = probe(FakeUiaDriver({"probe": window}, truncate_at=2)).observe("probe")
        return full.status is Status.PASS and clipped.status is Status.UNVERIFIED
