"""Grant helpers -- shared across all proof-surface boundaries.

proof-surface's action-authorization schema is CLOSED: it rejects any unexpected
field in ``scope``. Accountable-surface carries its own capability signals in the
same grant, and they have no meaning inside proof-surface's schema:

  ``allowed_perceptions``  which perceptions the operator permits.
  ``allowed_bounds``       which effector construction bounds the operator permits
                           (see ``bounds.py``).
  ``allowed_reads``        which read scopes the remote MCP layer may use for
                           preconditions, verification, rollback, and journal replay.
  ``allowed_irreversible_actions``
                           the exact action kinds the operator lets act without a
                           rollback (see ``irreversible_granted``). A list of kind
                           strings; no wildcard, boolean, or string form counts.

Strip them before handing any grant to propose() or actuate() so the schema check
never sees them.

This module is the SINGLE canonical place for that transform; import it from any
boundary that calls into proof-surface (world/session.py, server.py, …).
"""

from __future__ import annotations

LOCAL_SCOPE_FIELDS = ("allowed_perceptions", "allowed_bounds", "allowed_reads",
                      "allowed_irreversible_actions")


def irreversible_granted(grant, action_kind: str) -> bool:
    """True iff the grant lists `action_kind` in ``scope.allowed_irreversible_actions``.

    Only a list (or tuple) of exact kind strings counts. A string would turn the
    membership test into a substring test, and a wildcard would grant kinds the
    operator never named, so both read as "not granted"."""
    scope = grant.get("scope") if isinstance(grant, dict) else None
    kinds = scope.get("allowed_irreversible_actions") if isinstance(scope, dict) else None
    if not isinstance(kinds, (list, tuple)):
        return False
    return any(isinstance(k, str) and k == action_kind and k != "*" for k in kinds)


def action_authorization(grant):
    """Return a grant suitable for proof-surface's closed action-authorization schema.

    Strips every field in ``LOCAL_SCOPE_FIELDS`` from ``scope`` (copy -- never mutates
    the original). Total over non-dict / missing-field grants: returns the original
    unchanged when there is nothing to strip, so the call is always safe regardless of
    grant shape.
    """
    if not isinstance(grant, dict):
        return grant
    scope = grant.get("scope")
    if not isinstance(scope, dict):
        return grant
    strip = [k for k in LOCAL_SCOPE_FIELDS if k in scope]
    if not strip:
        return grant
    auth = dict(grant)
    auth["scope"] = {k: v for k, v in scope.items() if k not in strip}
    return auth
