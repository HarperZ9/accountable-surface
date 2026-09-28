"""No tool input schema carries authority or evasion (I9).

Grants, tiers, approvals, and `allow_irreversible` load out of band, so no
property anywhere in any schema is named for them, and none names a user
agent, proxy, headers, cookies, fingerprint, CAPTCHA, or stealth. The walker
descends nested objects and arrays; a planted schema proves it can fail.
"""

from __future__ import annotations

import re

import pytest
from test_mcp_annotations import listed

FORBIDDEN = ("grant", "authorization", "authorisation", "tier", "approval", "approve", "token", "allowirreversible",
             "useragent", "proxy", "headers", "cookie", "fingerprint", "captcha", "stealth", "webdriver", "solver")
ALLOWED = {"approval_id"}  # names a pending request to withdraw; carries no authority


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def walk(schema, path="") -> list[str]:
    out = []
    if isinstance(schema, dict):
        for key, sub in (schema.get("properties") or {}).items():
            out.append(f"{path}.{key}")
            out += walk(sub, f"{path}.{key}")
        for key in ("items", "additionalProperties"):
            if isinstance(schema.get(key), dict):
                out += walk(schema[key], f"{path}[]")
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in schema.get(key) or []:
                out += walk(sub, path)
    return out


def forbidden(schema) -> list[str]:
    hits = []
    for prop in walk(schema):
        leaf = prop.rsplit(".", 1)[-1]
        if leaf in ALLOWED:
            continue
        if any(word in _norm(leaf) for word in FORBIDDEN):
            hits.append(prop)
    return hits


def test_no_property_carries_authority_or_evasion():
    for where, tools in listed().items():
        for tool in tools:
            assert forbidden(tool.get("inputSchema") or {}) == [], (where, tool["name"])


@pytest.mark.parametrize("planted", [
    {"type": "object", "properties": {"allow_irreversible": {"type": "boolean"}}},
    {"type": "object", "properties": {"step": {"type": "object", "properties": {"grant": {"type": "object"}}}}},
    {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "object",
                                                                          "properties": {"userAgent": {}}}}}},
])
def test_the_walker_catches_a_planted_property(planted):
    assert forbidden(planted)
