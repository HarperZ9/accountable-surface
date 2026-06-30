"""The Accountable Surface -- a live seam where a model perceives and acts only
through accountability: witnessed perception, a pre-execution gate, and a
tamper-evident, durable memory, under human stewardship.

Mission: "Senses and sensibility are what lead to the new frontier. Machines
learning to hold themselves accountable."

The core (`surface`) is stdlib + coherence-membrane + proof-surface. The live
MCP server (`server`) additionally needs `mcp` (the `[server]` extra).
"""

from __future__ import annotations

from .effector import FilesystemEffector, Plan, RefusedActuation, Verdict
from .http_driver import HttpDriver, parse_html
from .os_effector import CommandEffector, SubprocessRunner
from .reference import ArxivSource, FakeSource, Grounding, Reference, ReferenceCortex, parse_arxiv_atom
from .surface import (
    AccountableSurface,
    ActionOutcome,
    ActuationOutcome,
    GoalOutcome,
    JournalEntry,
    Step,
)
from .web_effector import FakePageDriver, WebAction, WebEffector

__all__ = [
    "AccountableSurface",
    "ActionOutcome",
    "ActuationOutcome",
    "GoalOutcome",
    "Step",
    "JournalEntry",
    "FilesystemEffector",
    "Plan",
    "RefusedActuation",
    "Verdict",
    "WebEffector",
    "WebAction",
    "FakePageDriver",
    "HttpDriver",
    "parse_html",
    "CommandEffector",
    "SubprocessRunner",
    "ReferenceCortex",
    "Reference",
    "Grounding",
    "FakeSource",
    "ArxivSource",
    "parse_arxiv_atom",
]
__version__ = "0.1.0"
