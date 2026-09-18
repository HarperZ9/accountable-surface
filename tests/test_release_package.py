"""Release package boundaries."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sdist_ignores_dirty_local_runtime_directories(tmp_path):
    """Build from a private copy; never clean or mutate the source checkout."""

    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    source = tmp_path / "source"
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        tar.extractall(source, filter="data")

    (source / ".tmp-pytest" / "pytest-of-Zain" / "effectors").mkdir(parents=True)
    (source / ".tmp-pytest" / "pytest-of-Zain" / "effectors" / "state.txt").write_text(
        "private temp state", encoding="utf-8"
    )
    (source / ".venv" / "Lib" / "site-packages").mkdir(parents=True)
    (source / ".venv" / "Lib" / "site-packages" / "private.py").write_text(
        "SECRET = 'not for sdist'", encoding="utf-8"
    )

    out_dir = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(out_dir), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )

    [sdist] = out_dir.glob("accountable_surface-*.tar.gz")
    with tarfile.open(sdist, mode="r:gz") as tar:
        names = tar.getnames()

    assert names
    assert not any(".tmp-pytest" in name for name in names)
    assert not any(".venv" in name for name in names)
    assert not any("pytest-of-Zain" in name for name in names)
    assert any(name.endswith("src/accountable_surface/__init__.py") for name in names)
    assert any(name.endswith("tests/test_release_package.py") for name in names)

