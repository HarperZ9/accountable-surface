"""Grant helpers — shared across all proof-surface boundaries.

proof-surface's action-authorization schema is CLOSED: it rejects any unexpected
field in ``scope``. ``allowed_perceptions`` is accountable-surface's own
capability signal (which perceptions the operator permits) and has no meaning
inside proof-surface's schema. Strip it before handing any grant to propose() or
actuate() so the schema check never sees it.

This module is the SINGLE canonical place for that transform; import it from any
boundary that calls into proof-surface (world/session.py, server.py, …).
"""

from __future__ import annotations


def action_authorization(grant):
    """Return a grant suitable for proof-surface's closed action-authorization schema.

    Strips ``allowed_perceptions`` from ``scope`` (copy — never mutates the original).
    Total over non-dict / missing-field grants: returns the original unchanged when
    there is nothing to strip, so the call is always safe regardless of grant shape.
    """
    if not isinstance(grant, dict):
        return grant
    scope = grant.get("scope")
    if not (isinstance(scope, dict) and "allowed_perceptions" in scope):
        return grant
    auth = dict(grant)
    auth["scope"] = {k: v for k, v in scope.items() if k != "allowed_perceptions"}
    return auth
