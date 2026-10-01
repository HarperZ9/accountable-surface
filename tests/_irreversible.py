"""Test helper: a grant that also names its actions as irreversible-permitted.

Irreversible actuation needs the grant to list the action kind in
``scope.allowed_irreversible_actions``; the caller's ``allow_irreversible=True`` alone
authorizes nothing. Tests that exercise a pre-authorized irreversible act build their
grant through this helper so the authority is visible at the call site.
"""
from __future__ import annotations

import copy


def granting_irreversible(grant, *kinds):
    """Copy `grant` and list `kinds` (default: its allowed_actions) as irreversible-permitted."""
    out = copy.deepcopy(grant)
    scope = out.setdefault("scope", {})
    scope["allowed_irreversible_actions"] = list(kinds) or list(scope.get("allowed_actions", []))
    return out
