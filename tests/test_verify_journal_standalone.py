"""Standalone check on the vendored verify_journal.py. A stranger holding only the
journal file and this one script re-derives the hash chain: MATCH on an intact
journal, DRIFT on an edited-but-still-parsing entry, UNVERIFIABLE when the file is
absent. The script runs as a subprocess with PYTHONPATH stripped, so the test also
proves it needs nothing from the repo package on the path."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = REPO_ROOT / "verify_journal.py"
GENESIS = ""


def _line(prev: str, kind: str, summary: str, detail: dict) -> tuple[str, str]:
    """One on-disk journal line in the exact format the surface writes, plus its
    chain hash. Mirrors AccountableSurface._record byte for byte."""
    content = {"kind": kind, "summary": summary, "detail": detail}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    stored = hashlib.sha256(f"{prev}|{canonical}".encode("utf-8")).hexdigest()
    row = json.dumps({**content, "_prev": prev, "_hash": stored},
                     sort_keys=True, separators=(",", ":"))
    return row, stored


def _seed(path: Path) -> None:
    entries = [
        ("perception", "web: one", {"digest": "a", "title": "one"}),
        ("perception", "web: two", {"digest": "b", "title": "two"}),
        ("perception", "web: three", {"digest": "c", "title": "three"}),
    ]
    prev = GENESIS
    lines = []
    for kind, summary, detail in entries:
        row, prev = _line(prev, kind, summary, detail)
        lines.append(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(target: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)          # nothing from the repo on the path
    return subprocess.run([sys.executable, str(VERIFIER), str(target)],
                          capture_output=True, text=True, cwd=target.parent, env=env)


def test_intact_journal_matches(tmp_path):
    path = tmp_path / "j.jsonl"
    _seed(path)
    result = _run(path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_edited_field_is_drift(tmp_path):
    path = tmp_path / "j.jsonl"
    _seed(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["detail"]["title"] = "TAMPERED"      # a valid JSON edit, _hash left stale
    lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = _run(path)
    assert result.returncode == 1, result.stdout + result.stderr


def test_missing_journal_is_unverifiable(tmp_path):
    result = _run(tmp_path / "does-not-exist.jsonl")
    assert result.returncode == 2, result.stdout + result.stderr
