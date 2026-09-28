"""Replay and re-derivation cannot act (I10).

The replay CLI and the re-derivation it runs import nothing that defines an
effector's act: no effector module, no driver, no surface. A fresh interpreter
imports the replay entry point, and the test reads back which package modules
came with it. A planted import proves the check can fail.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTING = ("effector", "driver", "surface", "world", "uia", "command", "interop_runtime", "remote_actuation")

PROBE = """
import importlib, inspect, json, sys
importlib.import_module(sys.argv[1])
mods = sorted(m for m in sys.modules if m.startswith("accountable_surface"))
acting = []
for name in mods:
    mod = sys.modules[name]
    for attr, obj in vars(mod).items():
        if inspect.isclass(obj) and obj.__module__ == name and callable(getattr(obj, "act", None)):
            acting.append(f"{name}.{attr}")
print(json.dumps({"modules": mods, "acting": acting}))
"""


def _graph(entry: str, extra_path: str | None = None) -> dict:
    paths = [str(ROOT / "src")] + ([extra_path] if extra_path else []) + os.environ.get("PYTHONPATH", "").split(os.pathsep)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in paths if p)}
    out = subprocess.run([sys.executable, "-c", PROBE, entry], capture_output=True, text=True, env=env, check=True)
    return json.loads(out.stdout)


def _acting_modules(graph: dict) -> list[str]:
    """Package modules whose own name says they act (the package root excluded)."""
    return [m for m in graph["modules"] if m != "accountable_surface"
            and any(word in m.rsplit(".", 1)[-1] for word in ACTING)]


def test_replay_import_graph_reaches_no_act():
    for entry in ("accountable_surface.replay_cli", "accountable_surface.rederive"):
        graph = _graph(entry)
        assert entry in graph["modules"]
        assert _acting_modules(graph) == [], entry
        assert graph["acting"] == [], entry


def test_the_graph_check_catches_a_planted_effector_import(tmp_path):
    pkg = tmp_path / "planted_replay"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from accountable_surface import rederive, web_effector\n", encoding="utf-8")
    graph = _graph("planted_replay", str(tmp_path))
    assert "accountable_surface.web_effector" in _acting_modules(graph)
    assert any(name.endswith(".WebEffector") for name in graph["acting"])
