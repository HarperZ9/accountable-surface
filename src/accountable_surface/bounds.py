"""Effector bounds -- the reach an effector was constructed with, and whether an
operator grant covers it.

An effector's construction bound (a filesystem root, a working directory plus a
command allowlist, a set of origins) decides how far a gate `allow` can actually
travel. Until now that bound lived only in the constructor: the same unchanged
grant reached further when the effector was built wider, and the journal recorded
both actuations identically, so an auditor could not tell the narrow one from the
wide one.

`allowed_bounds` closes that. It is accountable-surface's own scope field, like
`allowed_perceptions`: proof-surface's action-authorization schema is CLOSED and
knows nothing about it, so `grant.action_authorization` strips it before the grant
crosses that boundary.

Coverage is containment, never equality of convenience:
  * a path facet is covered by the granted path itself or any ancestor of the
    effector's path, so a WIDER effector root stops matching a narrower grant;
  * a set facet (commands, origins, intents) is covered when the effector's set is a
    SUBSET of the granted set;
  * a facet the granted entry does not mention is not covered, and neither is a
    facet name this module does not know. Fail-closed in both directions.

Absent `allowed_bounds`, the grant places no bound on the effector and the journal
records the bound anyway. That is an honest null, not enforcement: the operator has
to write the field to get the refusal.
"""

from __future__ import annotations

from pathlib import PurePosixPath

PATH_FACETS = frozenset({"root", "cwd"})
SET_FACETS = frozenset({"commands", "origins", "intents"})


def bound_of(effector) -> dict | None:
    """The effector's declared construction bound, or None if it declares none."""
    declare = getattr(effector, "bound", None)
    if declare is None:
        return None
    bound = declare()
    return bound if isinstance(bound, dict) and bound.get("kind") else None


def render_bound(bound) -> str:
    """A stable one-line rendering, for journals and for refusal messages the
    operator can read the exact bound out of."""
    if not isinstance(bound, dict) or not bound.get("kind"):
        return "undeclared"
    facets = []
    for key in sorted(k for k in bound if k != "kind"):
        value = bound[key]
        rendered = ",".join(sorted(str(v) for v in value)) if isinstance(value, (list, tuple, set)) else str(value)
        facets.append(f"{key}={rendered}")
    return f"{bound['kind']}:" + " ".join(facets)


def _facet_covers(name, granted, actual) -> bool:
    if name in PATH_FACETS:
        g, a = PurePosixPath(str(granted)), PurePosixPath(str(actual))
        return g == a or g in a.parents
    if name in SET_FACETS:
        if not isinstance(granted, (list, tuple, set)) or not isinstance(actual, (list, tuple, set)):
            return False
        return set(str(v) for v in actual) <= set(str(v) for v in granted)
    return False  # a facet this module cannot reason about is never covered


def entry_covers(granted, actual) -> bool:
    """True iff one `allowed_bounds` entry covers the effector's actual bound."""
    if not isinstance(granted, dict) or not isinstance(actual, dict):
        return False
    if granted.get("kind") != actual.get("kind"):
        return False
    g_facets = {k: v for k, v in granted.items() if k != "kind"}
    a_facets = {k: v for k, v in actual.items() if k != "kind"}
    if set(g_facets) != set(a_facets):
        return False
    return all(_facet_covers(name, g_facets[name], value) for name, value in a_facets.items())


def bound_refusal(authorization, effector) -> str | None:
    """None when the grant permits this effector's reach; otherwise the reason.

    Returns None when `allowed_bounds` is absent (the grant does not speak about
    bounds). When it is present, an effector that declares no bound, or one whose
    bound no entry covers, is refused.
    """
    scope = (authorization or {}).get("scope") if isinstance(authorization, dict) else None
    if not isinstance(scope, dict) or "allowed_bounds" not in scope:
        return None
    granted = scope.get("allowed_bounds") or []
    actual = bound_of(effector)
    if actual is None:
        return "effector declares no bound, and the grant restricts allowed_bounds"
    if any(entry_covers(entry, actual) for entry in granted):
        return None
    return (
        f"effector bound {render_bound(actual)!r} is not covered by the grant's "
        f"allowed_bounds ({len(granted)} entr" + ("y" if len(granted) == 1 else "ies") + ")"
    )
