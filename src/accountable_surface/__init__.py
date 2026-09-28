"""The Accountable Surface -- a live seam where a model perceives and acts only
through accountability: witnessed perception, a pre-execution gate, and a
tamper-evident, durable memory, under human stewardship.

Mission: "Senses and sensibility are what lead to the new frontier. Machines
learning to hold themselves accountable."

The core (`surface`) is stdlib + coherence-membrane + proof-surface. The live
MCP server (`server`) additionally needs `mcp` (the `[server]` extra).

The public names below load on first use (PEP 562), not when the package is
imported. `from accountable_surface import AccountableSurface` works as before;
what changes is that importing a read-only submodule, such as the replay and
re-derivation modules, no longer drags every effector and driver in with it, so
a test can prove those modules reach no act path.
"""

from __future__ import annotations

import importlib

__version__ = "0.3.1"

_EXPORTS = {
    ".surface": ("AccountableSurface", "ActionOutcome", "ActuationOutcome", "GoalOutcome", "Step", "JournalEntry"),
    ".effector": ("FilesystemEffector", "Plan", "RefusedActuation", "Verdict"),
    ".web_effector": ("WebEffector", "WebAction", "FakePageDriver"),
    ".browser_effector": ("BrowserEffector", "BrowserAction", "BrowserDriver", "FakeBrowserDriver"),
    ".http_driver": ("HttpDriver", "parse_html"),
    ".os_effector": ("CommandEffector", "SubprocessRunner"),
    ".api_effector": ("ApiEffector", "ApiCall", "ApiOperation", "ApiService", "FakeApiDriver",
                      "GITHUB_ISSUE_COMMENTS"),
    ".credentials": ("MissingCredential", "require_secret", "has_secret"),
    ".registry": ("EffectorRegistry", "Exposed", "load_effectors"),
    ".reference": ("ReferenceCortex", "Reference", "Grounding", "FakeSource", "ArxivSource", "parse_arxiv_atom"),
    ".native_control_effector": ("NativeControlListEffector", "NativeControlWriteEffector", "NativeControlRunner",
                                 "FakeNativeControlRunner", "SAFE_READ_VERBS"),
    ".action_receipt": ("ActionReceiptReceptor", "receipt_from_outcome", "verify_receipts"),
}
_WHERE = {name: module for module, names in _EXPORTS.items() for name in names}

__all__ = [name for names in _EXPORTS.values() for name in names]


def __getattr__(name: str):
    module = _WHERE.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
