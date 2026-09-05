"""Actuation asked for by a remote caller -- the policy layer between an MCP tool
call and `AccountableSurface.actuate`.

`propose` is advisory and changes nothing, so exposing it costs little. `actuate`
writes. Everything here exists to make that difference explicit rather than to add
capability: the call is refused before an effector is touched unless two separate
operator decisions agree, and whatever happens comes back as a receipt with the
same shape, so a caller cannot read success out of the response's structure.

Order matters and is deliberate. The registry (what may be reached at all) is
checked BEFORE the grants, so a caller cannot make the server read its grants, or
journal an attempt, for a capability that was never exposed.

`allow_irreversible` is absent from this module by construction. There is no
argument a remote caller can pass that reaches it, so an irreversible plan stays
`needs-human` here whatever a grant says.
"""

from __future__ import annotations

from typing import Any

from accountable_surface.effector import RefusedActuation
from accountable_surface.grant import action_authorization
from accountable_surface.registry import EffectorRegistry
from accountable_surface.surface import AccountableSurface


def _refused(reason: str, **extra: Any) -> dict[str, Any]:
    """A refusal that never reached an effector. Nothing was perceived and nothing
    acted, so there is no journal entry to hand back. The shape matches a real
    receipt precisely so a caller cannot read success out of the shape."""
    payload: dict[str, Any] = {
        "decision": "deny", "acted": False, "verified": False,
        "verdict": "refused-before-actuation", "rolled_back": False,
        "reasons": [reason], "certificate": {}, "journal_entry": None,
    }
    payload.update(extra)
    return payload


def _grant_for(grants: list[dict], action_kind: str) -> tuple[dict | None, list[str]]:
    """The single grant this call runs under, and a note when more than one matched.

    First match wins on purpose. Proposing against every grant would run the gate
    once per grant and journal each attempt, so one refused call would spell out the
    operator's whole grant set to the caller. Honest null: a call therefore reaches
    only as far as the FIRST grant naming its action kind, even when a later grant is
    wider, and the note in the receipt says when that happened.
    """
    matching = [
        grant for grant in grants
        if action_kind in ((grant.get("scope") or {}).get("allowed_actions") or [])
    ]
    if not matching:
        return None, []
    if len(matching) > 1:
        return matching[0], [f"{len(matching)} grants name {action_kind!r}; the first one was used"]
    return matching[0], []


def _receipt(surface: AccountableSurface, outcome, notes: list[str], since: int) -> dict[str, Any]:
    """The journal entry for THIS call, and nothing else from the journal. The whole
    journal is the operator's; a caller gets back only what it just caused."""
    mine = [entry.to_dict() for entry in surface.journal[since:] if entry.kind == "actuation"]
    return {
        "decision": outcome.decision,
        "acted": outcome.acted,
        "verified": outcome.verified,
        "verdict": outcome.verdict,
        "rolled_back": outcome.rolled_back,
        "reasons": list(outcome.reasons) + notes,
        "certificate": outcome.certificate,
        "journal_entry": mine[-1] if mine else None,
    }


def actuate_impl(
    surface: AccountableSurface,
    grants: list[dict],
    registry: EffectorRegistry,
    action_kind: str,
    target: str,
    content: str,
    expected_digest: str | None = None,
    justification: str | None = None,
) -> dict[str, Any]:
    """Act through an exposed effector, or say why not."""
    exposed = registry.get(action_kind)
    if exposed is None:
        return _refused(
            f"action_kind {action_kind!r} is not exposed by this server",
            exposed_action_kinds=registry.action_kinds(),
        )
    grant, notes = _grant_for(grants, action_kind)
    if grant is None:
        return _refused(
            f"no operator grant names {action_kind!r} -- default-deny; the model cannot self-authorize"
        )
    try:
        payload = exposed.decode(content)
    except ValueError as exc:
        return _refused(f"content is not what {action_kind!r} accepts: {exc}")
    since = len(surface.journal)
    try:
        outcome = surface.actuate(
            exposed.effector, target=target, content=payload,
            authorization=action_authorization(grant),
            expected_digest=expected_digest, justification=justification,
        )
    except RefusedActuation as exc:
        # The effector can refuse while resolving the plan, before any state exists to
        # journal. That is a refusal and not a fault, so it comes back as a receipt.
        return _refused(f"the effector refused the plan before acting: {exc}")
    return _receipt(surface, outcome, notes, since)
