"""The declared version must agree everywhere it is written down.

accountable-surface declares its version in ``pyproject.toml`` for the built
distribution and as ``accountable_surface.__version__`` for the running package.
``mcp.py`` reports that module value in the MCP ``serverInfo`` block, so a client
asking which version it is talking to gets the module's answer, not the wheel's.

Nothing tied the two together. Both read ``0.1.0`` through the v0.1.0, v0.2.1 and
v0.3.0 tags, so every client saw ``0.1.0`` no matter which release was running.
The release workflow could not catch it: it checks the git tag against
``pyproject.toml`` and never reads the module.

The version is read with a regex rather than ``tomllib``. ``requires-python`` is
``>=3.10`` and ``tomllib`` arrived in 3.11, so importing it here would break the
suite for a supported interpreter.
"""
from __future__ import annotations

import pathlib
import re

import accountable_surface

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROJECT_VERSION = re.compile(
    r"^\[project\]$.*?^version\s*=\s*[\"']([^\"']+)[\"']",
    re.MULTILINE | re.DOTALL,
)


def _declared_version() -> str:
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = _PROJECT_VERSION.search(text)
    assert match is not None, "pyproject.toml has no [project] version"
    return match.group(1)


def test_the_declared_version_is_readable():
    # Guards the guard: a regex that silently stopped matching would make the
    # assertions below vacuous instead of failing.
    assert re.fullmatch(r"\d+\.\d+\.\d+", _declared_version())


def test_module_version_matches_the_declared_distribution_version():
    assert accountable_surface.__version__ == _declared_version()


def test_the_mcp_server_reports_the_declared_version():
    # The value a client actually receives, not just the constant behind it.
    from accountable_surface import mcp

    response = mcp.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    served = response["result"]["serverInfo"]["version"]
    assert served == _declared_version()


def test_the_changelog_has_an_entry_for_the_declared_version():
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = _declared_version()
    assert f"## {version}" in changelog, (
        f"CHANGELOG.md has no '## {version}' heading, so the release would ship "
        "without saying what changed")
