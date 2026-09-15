"""Protected operator authority paths for remote filesystem actuation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ProtectedPathHit:
    requested: str
    protected: str


class ProtectedPaths:
    """Small local boundary around grant, authority-state, and journal files."""

    def __init__(self, paths: Iterable[str | Path | None]) -> None:
        self._paths = tuple(path for raw in paths for path in _expanded(raw))
        self._keys = tuple(_path_keys(path) for path in self._paths)

    @classmethod
    def from_config(
        cls,
        *,
        grants_path: str | Path | None = None,
        authority_state_path: str | Path | None = None,
        journal_path: str | Path | None = None,
    ) -> "ProtectedPaths":
        paths: list[str | Path | None] = [grants_path, journal_path]
        if authority_state_path:
            state = Path(authority_state_path)
            paths.extend([state, Path(str(state) + "-wal"), Path(str(state) + "-shm")])
        return cls(paths)

    def deny_subjects(self, subjects: Iterable[str]) -> ProtectedPathHit | None:
        for subject in subjects:
            hit = self.deny_path(_subject_path(subject))
            if hit is not None:
                return hit
        return None

    def deny_path(self, path: Path | None) -> ProtectedPathHit | None:
        if path is None:
            return None
        candidate_keys = _path_keys(path)
        for protected, protected_keys in zip(self._paths, self._keys):
            if _overlaps(candidate_keys, protected_keys) or _identity_matches(path, protected):
                return ProtectedPathHit(str(path), str(protected))
        return None

    def digest(self) -> str:
        payload = sorted(sorted(keys) for keys in self._keys)
        return "sha256:" + sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _expanded(raw: str | Path | None) -> tuple[Path, ...]:
    if not raw:
        return ()
    path = Path(raw)
    return (path, Path(str(path) + ".tmp"), Path(str(path) + ".bak"))


def _subject_path(subject: str) -> Path | None:
    if not isinstance(subject, str) or not subject.startswith("file://"):
        return None
    return Path(subject[len("file://"):])


def _path_keys(path: Path) -> tuple[str, ...]:
    raw = _norm(path.absolute())
    resolved = _norm(path.resolve(strict=False))
    return (raw,) if raw == resolved else (raw, resolved)


def _identity_matches(left: Path, right: Path) -> bool:
    same = _samefile(left, right)
    if same is not None:
        return same
    left_stat = _stat(left)
    right_stat = _stat(right)
    if left_stat == "missing" or right_stat == "missing":
        return False
    if left_stat is None or right_stat is None:
        return True
    left_id, right_id = _stat_identity(left_stat), _stat_identity(right_stat)
    return True if left_id is None or right_id is None else left_id == right_id


def _samefile(left: Path, right: Path) -> bool | None:
    try:
        return os.path.samefile(left, right)
    except FileNotFoundError:
        return False
    except OSError:
        return None


def _stat(path: Path):
    try:
        return path.stat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return None


def _stat_identity(stat_result) -> tuple[int, int] | None:
    dev, ino = getattr(stat_result, "st_dev", None), getattr(stat_result, "st_ino", None)
    return None if dev is None or ino in (None, 0) else (int(dev), int(ino))


def _norm(path: Path) -> str:
    return os.path.normcase(str(path))


def _overlaps(lefts: tuple[str, ...], rights: tuple[str, ...]) -> bool:
    return any(_same_or_nested(left, right) or _same_or_nested(right, left) for left in lefts for right in rights)


def _same_or_nested(child: str, parent: str) -> bool:
    try:
        Path(child).relative_to(Path(parent))
        return True
    except ValueError:
        return False
