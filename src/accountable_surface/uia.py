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

Two listings read UNVERIFIED, because neither can establish that a control is absent:

  * A TRUNCATED tree is a partial view. An element that exists can read as absent, so
    any check resting on absence has to refuse instead of passing. This one announces
    itself.
  * An OPAQUE tree is the quiet one. The walk finished, nothing was cut, and nothing
    it saw carried a name, which is the same answer a window with no such control
    gives. Nothing about it looks partial.

`uia.ps1` states a `settlesAbsence` of its own and the organ derives the same bit
from the facts. The instrument's claim is taken as a veto and never as a promotion,
so the thing being measured cannot decide that the measurement counts.

A label two controls carry is refused on every rung, matching the instrument. An
AutomationId is the way past it, and a plan that names one thing twice is a plan
that has not said what it means to act on.
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
    offline as it does against a live window: UNIQUE exact name, then UNIQUE exact
    AutomationId, then a unique substring of a name. Every comparison ignores case,
    because PowerShell's `-eq` on strings does.

    A label carried by two controls is refused on every rung. Taking the first hit
    would resolve a plan that the live rung refuses, which is worse than either
    behaviour on its own: the offline answer would say a control is reachable and the
    window would say it is not.

    Returns `{"status": "ok", "index": .., "how": ..}` or a refusal carrying `status`
    "ambiguous", "none", or "invalid".
    """
    if not needle:
        return {"status": "invalid", "reason": "empty match"}
    folded = needle.lower()
    for how, field in (("name-exact", "name"), ("automationid-exact", "automationId")):
        hits = [i for i, e in enumerate(elements)
                if str(e.get(field) or "").lower() == folded]
        chosen = _one_of(elements, hits, how)
        if chosen is not None:
            return chosen
    hits = [i for i, e in enumerate(elements) if folded in str(e.get("name") or "").lower()]
    chosen = _one_of(elements, hits, "name-substring-unique", ambiguous_as="name-substring")
    return chosen if chosen is not None else {"status": "none"}


def _one_of(elements: list, hits: list, how: str, *,
            ambiguous_as: str | None = None) -> dict | None:
    """One hit resolves, several refuse, none defers to the next rung.

    Candidates are named rather than counted, because the caller's next move is to
    pick a label that separates them and a count cannot be acted on.
    """
    if len(hits) == 1:
        return {"status": "ok", "index": hits[0], "how": how}
    if hits:
        return {"status": "ambiguous", "how": ambiguous_as or how,
                "candidates": [elements[i].get("name") for i in hits[:10]]}
    return None


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
        truncated = limit is not None and len(elements) > limit
        return {"ok": True, "window": title, "count": len(shown),
                "descendants": len(elements), "max": limit,
                "truncated": truncated, "opaque": not shown,
                "settlesAbsence": bool(shown) and not truncated,
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
        # A walk that finished and saw nothing named is the quiet way a read fails. It
        # is shaped exactly like a window holding no such control, and nothing in the
        # answer tells the two apart, so on its own it settles nothing.
        opaque = bool(answer.get("ok")) and not elements
        settled = bool(answer.get("ok")) and not truncated and not opaque
        # `uia.ps1` states its own settlesAbsence. Reading it verbatim would let the
        # instrument's claim stand in for the facts, so it is taken as a veto and never
        # as a promotion: the claim and the derivation have to agree.
        claimed = answer.get("settlesAbsence")
        if claimed is not None:
            settled = settled and bool(claimed)
        if answer.get("ok"):
            summary = f"{window}: {len(elements)} controls"
            if truncated:
                summary += " (TRUNCATED -- absence is not established)"
            elif opaque:
                summary += " (OPAQUE -- absence is not established)"
        else:
            summary = f"{window}: {answer.get('error') or 'unreadable'}"
        return Observation(
            organ=self.name,
            subject=f"{SCHEME}{window}",
            summary=summary,
            # A partial tree is a partial view, and an opaque one is a view of
            # nothing: either way a control that exists can read as absent, so
            # neither settles anything about absence.
            status=Status.PASS if settled else Status.UNVERIFIED,
            provenance=Provenance.witness_bytes(
                f"{SCHEME}{window}", canon(elements), "high" if settled else "moderate",
                command=f"uia.ps1 tree {window} {self._max}",
            ),
            data={"window": window, "ok": bool(answer.get("ok")), "elements": elements,
                  "truncated": truncated, "opaque": opaque,
                  "settles_absence": settled,
                  "descendants": answer.get("descendants"),
                  "sha256": sha256_hex(canon(elements))},
        )

    def selftest(self) -> bool:
        """Falsifiable: neither a clipped tree nor an empty one is a settled read.

        The empty case is here because it is the one that looks fine. A clipped read
        announces itself; a read that came back whole with nothing named announces
        nothing at all, and reads as a window with no controls.

        Probes `type(self)` rather than this class by name, so an organ that wraps or
        replaces the read cannot inherit a green selftest for behaviour it does not
        have."""
        window = FakeWindow(elements=[{"name": f"control-{i}"} for i in range(3)])
        probe = type(self)
        full = probe(FakeUiaDriver({"probe": window})).observe("probe")
        clipped = probe(FakeUiaDriver({"probe": window}, truncate_at=2)).observe("probe")
        blind = probe(FakeUiaDriver({"probe": FakeWindow()})).observe("probe")
        return (full.status is Status.PASS and clipped.status is Status.UNVERIFIED
                and blind.status is Status.UNVERIFIED)
