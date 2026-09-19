"""The Accountable Surface -- a live seam where a model perceives and acts only
through accountability: witnessed perception, a pre-execution gate, and a
tamper-evident, durable memory, under human stewardship.

Mission: "Senses and sensibility are what lead to the new frontier. Machines
learning to hold themselves accountable."

The core (`surface`) is stdlib + coherence-membrane + proof-surface. The live
MCP server (`server`) additionally needs `mcp` (the `[server]` extra).

The perception/gate/actuation names below are re-exported lazily (PEP 562): they
load their submodule -- and the sibling repos it needs -- only on first attribute
access. So `import accountable_surface` and the bundled-lane health surface
`accountable_surface.mcp` stay stdlib-only and import even where the sibling repos
are not installed, while `from accountable_surface import AccountableSurface` still
resolves on demand exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.1.0"

# Re-exported name -> the submodule that defines it. Each submodule pulls in the
# coherence-membrane sibling repo, so the import is deferred to first access.
_LAZY_EXPORTS = {
    "AccountableSurface": "surface",
    "ActionOutcome": "surface",
    "ActuationOutcome": "surface",
    "GoalOutcome": "surface",
    "JournalEntry": "surface",
    "Step": "surface",
    "FilesystemEffector": "effector",
    "Plan": "effector",
    "RefusedActuation": "effector",
    "Verdict": "effector",
    "HttpDriver": "http_driver",
    "parse_html": "http_driver",
    "CommandEffector": "os_effector",
    "SubprocessRunner": "os_effector",
    "ReferenceCortex": "reference",
    "Reference": "reference",
    "Grounding": "reference",
    "FakeSource": "reference",
    "ArxivSource": "reference",
    "parse_arxiv_atom": "reference",
    "WebEffector": "web_effector",
    "WebAction": "web_effector",
    "FakePageDriver": "web_effector",
    "BrowserEffector": "browser_effector",
    "BrowserAction": "browser_effector",
    "BrowserDriver": "browser_effector",
    "FakeBrowserDriver": "browser_effector",
}


def __getattr__(name: str) -> object:
    """Import a re-exported name's submodule on demand (PEP 562)."""
    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(f".{module}", __name__), name)
    globals()[name] = value  # cache so later access skips __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:  # give type checkers and IDEs the real names.
    from .browser_effector import (
        BrowserAction,
        BrowserDriver,
        BrowserEffector,
        FakeBrowserDriver,
    )
    from .effector import FilesystemEffector, Plan, RefusedActuation, Verdict
    from .http_driver import HttpDriver, parse_html
    from .os_effector import CommandEffector, SubprocessRunner
    from .reference import (
        ArxivSource,
        FakeSource,
        Grounding,
        Reference,
        ReferenceCortex,
        parse_arxiv_atom,
    )
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
    "BrowserEffector",
    "BrowserAction",
    "BrowserDriver",
    "FakeBrowserDriver",
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
    "__version__",
]
