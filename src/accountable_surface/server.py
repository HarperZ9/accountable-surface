"""Accountable Surface MCP server.

Remote tools require registry exposure, out-of-band grants, and explicit read authority
for target state and journal replay. Fresh installs default-deny remote mutation and journal reads.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from accountable_surface import __version__
from accountable_surface.authority_store import AuthorityState, AuthorityStore, load_operator_grants
from accountable_surface.grant import action_authorization
from accountable_surface.read_authority import (
    active_operator_grants,
    describe_journal_read,
    describe_web_read,
    grant_digest,
    select_read_decision,
)
from accountable_surface.registry import load_effectors
from accountable_surface.remote_actuation import actuate_impl
from accountable_surface.surface import AccountableSurface


def load_journal_path(path_str: str | None = None) -> Path | None:
    """Resolve the durable-journal path from the arg or ACCOUNTABLE_SURFACE_JOURNAL.
    None when unset -- the surface stays in-memory. Persistence is opt-in and
    supplied out-of-band by the operator, never by the model."""
    path_str = path_str or os.environ.get("ACCOUNTABLE_SURFACE_JOURNAL")
    return Path(path_str) if path_str else None


def perceive_impl(surface: AccountableSurface, subject: str) -> dict[str, Any]:
    return surface.perceive(subject).to_dict()


def remote_perceive_impl(surface: AccountableSurface, authority: AuthorityStore, subject: str) -> dict[str, Any]:
    try:
        request = describe_web_read(subject, "perceive")
    except ValueError as exc:
        return {"decision": "deny", "reasons": [f"read authority cannot describe this subject: {exc}"]}
    state = authority.load_for_remote_call()
    decision = select_read_decision(state.grants, request)
    if decision.verdict != "allow":
        reasons = [state.reason] if state.reason and not state.grants else decision.reasons
        return {"decision": decision.verdict, "reasons": reasons, "read_decision": decision.to_dict()}
    return {
        "decision": "allow",
        "observation": surface.perceive(subject).to_dict(),
        "read_decision": decision.to_dict(),
    }


def session_journal_impl(surface: AccountableSurface, authority: AuthorityStore) -> dict[str, Any]:
    state = authority.load_for_remote_call()
    decision = select_read_decision(state.grants, describe_journal_read("session", "journal-session"))
    if decision.verdict == "allow":
        return {"decision": "allow", "entries": [entry.to_dict() for entry in surface.journal],
                "read_decision": decision.to_dict()}
    if _has_read_scope(state.grants, "journal.own-session"):
        return {"decision": "needs-human", "reasons": ["journal.own-session is not bindable over stdio"]}
    own_call = select_read_decision(state.grants, describe_journal_read("own-call", "journal-own-call"))
    if own_call.verdict == "allow":
        return {"decision": "allow", "entries": [], "read_decision": own_call.to_dict()}
    return {"decision": "deny", "reasons": [state.reason or "no journal read authority matches session replay"]}


def remote_interocept_impl(surface: AccountableSurface) -> dict[str, Any]:
    observed = surface.interocept().to_dict()
    data = dict(observed.get("data") or {})
    data.pop("entries", None)
    observed["data"] = data
    return observed


def _has_read_scope(grants: list[dict], kind: str) -> bool:
    for grant in grants:
        for scope in ((grant.get("scope") or {}).get("allowed_reads") or []):
            if isinstance(scope, dict) and scope.get("observation_kind") == kind:
                return True
    return False


def _outcome_dict(outcome) -> dict[str, Any]:
    return {
        "decision": outcome.decision,
        "reasons": outcome.reasons,
        "checks": outcome.checks,
        "executed": outcome.executed,
    }


def propose_impl(
    surface: AccountableSurface,
    grants: list[dict],
    action_kind: str,
    target: str,
    expected_digest: str | None = None,
    observation=None,
) -> dict[str, Any]:
    """Check a proposed action against the operator's loaded grants. Allow iff
    some grant permits it (and state, if checked, passes); otherwise the most
    cautious outcome (needs-human over deny is not escalated -- deny stands if no
    grant allows). Default-deny when no grant is loaded."""
    if not grants:
        return {
            "decision": "deny",
            "reasons": ["no operator grant is loaded -- default-deny; the model cannot self-authorize"],
            "checks": {"authorization": "fail"},
            "executed": False,
        }
    outcomes = [
        surface.propose(
            action_kind=action_kind,
            target=target,
            authorization=action_authorization(grant),
            observation=observation,
            expected_digest=expected_digest,
        )
        for grant in grants
    ]
    for outcome in outcomes:
        if outcome.decision == "allow":
            return _outcome_dict(outcome)
    for outcome in outcomes:
        if outcome.decision == "needs-human":
            return _outcome_dict(outcome)
    return _outcome_dict(outcomes[0])


# --- the live MCP server ---------------------------------------------------

_surface = AccountableSurface(journal_path=load_journal_path())
_authority = AuthorityStore()
_registry = load_effectors()
mcp = FastMCP("accountable-surface")


@mcp.tool()
def perceive(subject: str) -> dict:
    """Perceive a web page or artifact as a witnessed Observation (URL, file
    path). Returns the observation with its provenance digest -- a structural
    reading, never a screenshot."""
    return remote_perceive_impl(_surface, _authority, subject)


@mcp.tool()
def propose(action_kind: str, target: str, expected_digest: str | None = None) -> dict:
    """Propose an action on a target. It is checked against the operator's
    pre-loaded authorization grants by the pre-execution gate (allow / deny /
    needs-human). The model cannot supply authorization; the surface never
    executes -- it returns the advisory decision for the operator to enforce."""
    return propose_impl(_surface, _authority.load_for_remote_call().grants, action_kind, target, expected_digest)


@mcp.tool()
def actuate(action_kind: str, target: str, content: str,
            expected_digest: str | None = None, justification: str | None = None,
            idempotency_key: str | None = None) -> dict:
    """Actually perform an action and verify it landed: perceive the target, plan,
    check the operator's gate, act, re-perceive, verify against the plan, and roll
    back a reversible action that did not verify.

    Reaches only the effectors the operator exposed (none by default) and only
    under a grant naming this action_kind. `content` is text for a file write, or
    {"intent": "...", "body": {...}} for an API call. Returns the decision, the
    verdict, and this call's journal entry -- no part of the rest of the journal."""
    return actuate_impl(_surface, _authority, _registry, action_kind, target, content,
                        expected_digest=expected_digest, justification=justification,
                        idempotency_key=idempotency_key)


@mcp.tool()
def session_journal() -> dict:
    """Return every perception and decision in the journal -- including entries
    replayed from prior sessions when ACCOUNTABLE_SURFACE_JOURNAL persistence is
    enabled."""
    return session_journal_impl(_surface, _authority)


@mcp.tool()
def interocept() -> dict:
    """Perceive the surface's own session: a witnessed, tamper-evident view of
    what it has perceived and what the gate decided (counts + a journal digest).
    The model sensing itself -- it grants no authority and mutates nothing."""
    return remote_interocept_impl(_surface)


def _status_payload() -> dict:
    return {"ok": True, "server": "accountable-surface", "version": __version__}


def _doctor_payload() -> dict:
    return {"ok": True, "server": "accountable-surface", "version": __version__,
            "grants_loaded": len(_authority.load_for_remote_call().grants),
            "journal_persistent": load_journal_path() is not None,
            "effectors": _registry.describe(),
            "tools": ["perceive", "propose", "actuate", "session_journal",
                      "interocept", "status", "doctor"]}


@mcp.tool()
def status() -> dict:
    """Liveness and identity of the Accountable Surface MCP server. Network-free:
    no perception, no gate, no actuation -- a fast health probe (the Flywheel lane
    roster marks the lane live only when this answers)."""
    return _status_payload()


@mcp.tool()
def doctor() -> dict:
    """Readiness: identity, the exposed tools, whether operator grants are loaded,
    which effectors are actuable (with the reach of each and every spec entry that
    was refused), and whether the journal is durable. No perception, no actuation."""
    return _doctor_payload()


def main() -> None:
    """Console entry point -- run the Accountable Surface as an MCP stdio server."""
    mcp.run()


if __name__ == "__main__":
    main()
