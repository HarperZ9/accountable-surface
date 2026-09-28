"""The small pieces the actuation pipeline composes: the identity field each
effector's perception carries, the default independent reader, the view that
lowers a plan's reversible bit, the per-step context, and two predicates over
a step's evidence and decision. Kept apart so pipeline.py stays one screen of
orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from accountable_surface.detectors import challenge, secrets
from accountable_surface.page_evidence import capture, from_snapshot
from accountable_surface.pipeline_record import PlanRef

IDENTITY_FIELDS = {"web-effector": "page_digest", "browser-effector": "page_digest",
                   "fs-effector": "sha256", "api-effector": "sha256"}


def default_reader(url: str):
    return capture(url, redactor=secrets.redact)


class IrreversibleView:
    """Delegates every method and lowers the plan's reversible bit, so an R7 hit
    needs `allow_irreversible` at the surface (the effector plans clicks reversible)."""

    def __init__(self, effector: Any) -> None:
        self._effector = effector

    def __getattr__(self, name: str) -> Any:
        return getattr(self._effector, name)

    def preview(self, target, content, before=None):
        return replace(self._effector.preview(target, content, before), reversible=False)


@dataclass
class Context:
    step: Any
    target: str
    content: Any
    reversible: bool
    now: str
    paused: frozenset
    before: Any = None
    effector_before: Any = None
    approval: dict | None = None
    plan: PlanRef | None = None
    refs: dict | None = None


def shows_challenge(snapshot, reader) -> bool:
    return bool(challenge.scan(from_snapshot(snapshot)) or (reader and challenge.scan(reader)))


def has(decision, rule: str) -> bool:
    return any(h["rule"] == rule for h in decision.rule_hits)
