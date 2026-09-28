"""verify_actuation.py: a stranger checks a session with Python alone.

The script at the repository root imports only the standard library, runs under
`python -I` with no package on the path, and re-derives L0 (the chain) and,
given the evidence folder, L1 (every blob re-hashes and the receipt's before
digest is the stored page). Exit codes follow the two existing verifiers:
0 MATCH, 1 DRIFT, 2 UNVERIFIABLE. Its labels agree with the package's own
re-derivation on the same tampering.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from actuation_site import Site
from actuation_world import World, mixed_session

from accountable_surface import rederive

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "verify_actuation.py"


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


@pytest.fixture
def world(tmp_path, site):
    w = World(tmp_path / "session", site)
    mixed_session(w)
    return w


def standalone(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                         env=env, cwd=str(Path(args[0]).parent) if args else None)
    return out.returncode, out.stdout


def test_imports_only_the_standard_library():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names and names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_runs_with_no_package_import(world):
    code, out = standalone(world.receipts.path, "--evidence", world.evidence.root)
    assert code == 0 and out.startswith("MATCH"), out


def test_without_evidence_it_checks_the_chain_and_says_so(world):
    code, out = standalone(world.receipts.path)
    assert code == 0 and out.startswith("MATCH") and "L0 only" in out


def _blob(world, seq, key):
    record = world.receipt_lines()[seq]
    ref = record["evidence"][key] if key in ("inputs", "after") else record["before"]["evidence"]
    return world.evidence.path_for(ref)


def test_exit_codes(world, tmp_path):
    receipts, store = world.receipts.path, world.evidence.root
    assert standalone(tmp_path / "missing.jsonl")[0] == 2
    blob = _blob(world, 2, "after")
    saved = blob.read_bytes()
    blob.unlink()
    assert standalone(receipts, "--evidence", store)[0] == 2
    blob.write_bytes(saved.replace(b"weekly notes", b"weekly nodes"))
    assert standalone(receipts, "--evidence", store)[0] == 1
    blob.write_bytes(saved)
    assert standalone(receipts, "--evidence", store)[0] == 0
    receipts.write_bytes(receipts.read_bytes().replace(b'"acted"', b'"stopped"', 1))
    code, out = standalone(receipts, "--evidence", store)
    assert code == 1 and out.startswith("DRIFT")


@pytest.mark.parametrize("tamper", ["none", "missing-before", "edited-inputs", "edited-reader", "edited-receipt"])
def test_agrees_with_the_package_at_l0_and_l1(world, tamper):
    if tamper == "missing-before":
        _blob(world, 2, "before").unlink()
    elif tamper == "edited-inputs":
        path = _blob(world, 3, "inputs")
        path.write_bytes(path.read_bytes() + b" ")
    elif tamper == "edited-reader":
        afters = [world.evidence.load(r["evidence"]["after"]) for r in world.receipt_lines()[1:]
                  if r["evidence"] and r["evidence"]["after"]]
        reader = next(a["reader"] for a in afters if a and a.get("reader"))
        world.evidence.path_for(reader).write_bytes(b"{}")
    elif tamper == "edited-receipt":
        path = world.receipts.path
        path.write_bytes(path.read_bytes().replace(b'"needs-human"', b'"acted"', 1))
    label = rederive.rederive(world.receipts.path, world.evidence.root, level="evidence")["verdict"]
    code, out = standalone(world.receipts.path, "--evidence", world.evidence.root)
    assert out.split()[0] == label and code == {"MATCH": 0, "DRIFT": 1, "UNVERIFIABLE": 2}[label], out
