"""Read and write are separate tools in the plugin profile.

The directory rejects a tool that takes both safe and unsafe operations. The
legacy `actuate` carries both a read verb (native.device.ls) and, in principle,
writes, so it lives only in the interop profile. The plugin profile carries
`device_ls` as its own read tool and one write tool per action class, which
also lets an operator allow a navigation unprompted and keep a submit prompting.
"""

from __future__ import annotations

from accountable_surface import tool_catalog


def test_no_plugin_tool_takes_both_read_and_write_kinds():
    for name in tool_catalog.names("plugin"):
        spec = tool_catalog.spec(name)
        assert spec.mode in ("read", "write"), name
        kinds = set(spec.kinds)
        if spec.mode == "read":
            assert not kinds & tool_catalog.WRITE_KINDS, name
        else:
            assert not kinds & tool_catalog.READ_KINDS, name


def test_the_mixed_legacy_tool_is_interop_only():
    mixed = [n for n in tool_catalog.names("interop") if tool_catalog.spec(n).mode == "mixed"]
    assert mixed == ["accountable-surface.actuate"]
    assert all(tool_catalog.spec(n).mode != "mixed" for n in tool_catalog.names("plugin"))


def test_the_read_verb_has_its_own_read_tool():
    spec = tool_catalog.spec("device_ls")
    assert spec.mode == "read" and spec.kinds == ("native.device.ls",) and spec.read_only


def test_each_write_class_has_its_own_tool():
    by_kind = {}
    for name in tool_catalog.names_by_mode("plugin", "write"):
        for kind in tool_catalog.spec(name).kinds:
            by_kind.setdefault(kind, set()).add(name)
    assert by_kind["web.submit"] == {"browser_submit", "run_plan"}
    assert "browser_navigate" not in by_kind["web.submit"]
    assert tool_catalog.spec("browser_navigate").kinds == ("web.navigate", "browser.navigate")


def test_no_tool_named_for_evaluate_or_a_command_in_the_plugin_profile():
    names = " ".join(tool_catalog.names("plugin"))
    assert "evaluate" not in names and "command" not in names and "os_run" not in names
