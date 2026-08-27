"""The network-free health tools the Flywheel lane roster probes.

status / doctor perceive nothing, gate nothing, actuate nothing -- they only report
identity and readiness, so a lane probe can mark the surface live without touching
the world.
"""
from accountable_surface import __version__
from accountable_surface.server import _doctor_payload, _status_payload


def test_status_is_network_free_identity():
    s = _status_payload()
    assert s["ok"] is True
    assert s["server"] == "accountable-surface"
    assert s["version"] == __version__


def test_doctor_reports_tools_and_readiness():
    d = _doctor_payload()
    assert d["ok"] is True and d["server"] == "accountable-surface"
    # the probe matches the bare tool names; both must be advertised
    assert "status" in d["tools"] and "doctor" in d["tools"]
    assert isinstance(d["grants_loaded"], int)
    assert isinstance(d["journal_persistent"], bool)
