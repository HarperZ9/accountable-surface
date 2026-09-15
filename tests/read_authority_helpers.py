"""Shared read-authority grant fixtures for remote MCP tests."""

from __future__ import annotations

from typing import Any

from accountable_surface.api_effector import GITHUB_ISSUE_COMMENTS
from accountable_surface.read_authority import describe_filesystem_read
from accountable_surface.registry import Exposed, _decode_bytes


def fs_reads(root, paths=("**",)):
    return [{
        "observation_kind": "fs.bytes",
        "phases": ["before", "backup", "after", "rollback"],
        "target_scope": {"kind": "fs", "root": str(root), "paths": list(paths)},
    }]


def api_reads():
    op = GITHUB_ISSUE_COMMENTS.operations[0]
    return [{
        "observation_kind": "api.resource",
        "phases": ["before", "after", "rollback"],
        "target_scope": {
            "kind": "api",
            "service": "github",
            "origins": [GITHUB_ISSUE_COMMENTS.origin],
            "intents": [op.intent],
            "paths": [op.path_shape],
        },
    }]


def fs_exposed(action_kind: str, effector: Any, root: Any, describe: str = "test") -> Exposed:
    return Exposed(
        action_kind,
        effector,
        _decode_bytes,
        describe,
        lambda target, payload, phase, request_id: describe_filesystem_read(root, target, phase, request_id),
        lambda payload: ("before", "backup", "after", "rollback"),
    )
