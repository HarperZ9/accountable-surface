"""Accountable Surface -- live MCP server (Phase 2-proper, step a).

Exposes the accountable surface as MCP tools a model calls in-session:

  * perceive(subject)        -- a witnessed Observation (URL / path / bytes-as-text),
                               never a screenshot.
  * propose(action_kind,target,expected_digest?)
                             -- checked against the OPERATOR's pre-loaded
                               authorization grants by proof-surface's
                               pre-execution gate (allow / deny / needs-human).
                               The model CANNOT supply its own authorization --
                               will-from-a-human is not a signal the model emits.
  * actuate(action_kind,target,content)
                             -- the loop closed: perceive, plan, gate, ACT,
                               re-perceive, verify. Two operator decisions have
                               to agree first. The registry says which effectors
                               a caller can reach at all (empty by default), and
                               a grant says what may be done with one. The caller
                               gets back the journal entry for its own action.
  * session_journal()        -- every perception and decision, recorded.

Operator grants load at launch from the JSON file named in
ACCOUNTABLE_SURFACE_GRANTS (one grant or a list). With none loaded the gate is
default-deny: the surface perceives freely but authorizes nothing.

The exposed effectors load from ACCOUNTABLE_SURFACE_EFFECTORS (see `registry`).
Unset → nothing is actuable, whatever the grants say.

The session journal persists to the append-only JSONL file named in
ACCOUNTABLE_SURFACE_JOURNAL when set, and replays on launch -- so the witnessed
self-view (interocept) spans sessions. Unset → the journal is in-memory only.

Additive: a new standalone component. It does NOT touch ORCA. Requires `mcp`
plus coherence-membrane and proof-surface on the path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from accountable_surface import __version__
from accountable_surface.grant import action_authorization
from accountable_surface.registry import load_effectors
from accountable_surface.remote_actuation import actuate_impl
from accountable_surface.surface import AccountableSurface


def load_operator_grants(path_str: str | None = None) -> list[dict]:
    """Load operator authorization grants from a JSON file (one grant or a list).
    Absent/unreadable/invalid -> [] (default-deny). The grants are the operator's
    will, supplied out-of-band; the model never provides them."""
    path_str = path_str or os.environ.get("ACCOUNTABLE_SURFACE_GRANTS")
    if not path_str:
        return []
    try:
        data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [g for g in data if isinstance(g, dict)]
    return []


def load_journal_path(path_str: str | None = None) -> Path | None:
    """Resolve the durable-journal path from the arg or ACCOUNTABLE_SURFACE_JOURNAL.
    None when unset -- the surface stays in-memory. Persistence is opt-in and
    supplied out-of-band by the operator, never by the model."""
    path_str = path_str or os.environ.get("ACCOUNTABLE_SURFACE_JOURNAL")
    return Path(path_str) if path_str else None


def perceive_impl(surface: AccountableSurface, subject: str) -> dict[str, Any]:
    return surface.perceive(subject).to_dict()


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
_grants = load_operator_grants()
_registry = load_effectors()
mcp = FastMCP("accountable-surface")


@mcp.tool()
def perceive(subject: str) -> dict:
    """Perceive a web page or artifact as a witnessed Observation (URL, file
    path). Returns the observation with its provenance digest -- a structural
    reading, never a screenshot."""
    return perceive_impl(_surface, subject)


@mcp.tool()
def propose(action_kind: str, target: str, expected_digest: str | None = None) -> dict:
    """Propose an action on a target. It is checked against the operator's
    pre-loaded authorization grants by the pre-execution gate (allow / deny /
    needs-human). The model cannot supply authorization; the surface never
    executes -- it returns the advisory decision for the operator to enforce."""
    return propose_impl(_surface, _grants, action_kind, target, expected_digest)


@mcp.tool()
def actuate(action_kind: str, target: str, content: str,
            expected_digest: str | None = None, justification: str | None = None) -> dict:
    """Actually perform an action and verify it landed: perceive the target, plan,
    check the operator's gate, act, re-perceive, verify against the plan, and roll
    back a reversible action that did not verify.

    Reaches only the effectors the operator exposed (none by default) and only
    under a grant naming this action_kind. `content` is text for a file write, or
    {"intent": "...", "body": {...}} for an API call. Returns the decision, the
    verdict, and this call's journal entry -- no part of the rest of the journal."""
    return actuate_impl(_surface, _grants, _registry, action_kind, target, content,
                        expected_digest=expected_digest, justification=justification)


@mcp.tool()
def session_journal() -> list:
    """Return every perception and decision in the journal -- including entries
    replayed from prior sessions when ACCOUNTABLE_SURFACE_JOURNAL persistence is
    enabled."""
    return [entry.to_dict() for entry in _surface.journal]


@mcp.tool()
def interocept() -> dict:
    """Perceive the surface's own session: a witnessed, tamper-evident view of
    what it has perceived and what the gate decided (counts + a journal digest).
    The model sensing itself -- it grants no authority and mutates nothing."""
    return _surface.interocept().to_dict()


def _status_payload() -> dict:
    return {"ok": True, "server": "accountable-surface", "version": __version__}


def _doctor_payload() -> dict:
    return {"ok": True, "server": "accountable-surface", "version": __version__,
            "grants_loaded": len(_grants),
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
