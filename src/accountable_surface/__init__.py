"""The Accountable Surface — a live seam where a model perceives and acts only
through accountability: witnessed perception, a pre-execution gate, and a
tamper-evident, durable memory, under human stewardship.

Mission: "Senses and sensibility are what lead to the new frontier. Machines
learning to hold themselves accountable."

The core (`surface`) is stdlib + coherence-membrane + proof-surface. The live
MCP server (`server`) additionally needs `mcp` (the `[server]` extra).
"""

from __future__ import annotations

from .effector import FilesystemEffector, Plan, RefusedActuation, Verdict
from .surface import AccountableSurface, ActionOutcome, ActuationOutcome, JournalEntry

__all__ = [
    "AccountableSurface",
    "ActionOutcome",
    "ActuationOutcome",
    "JournalEntry",
    "FilesystemEffector",
    "Plan",
    "RefusedActuation",
    "Verdict",
]
__version__ = "0.1.0"
