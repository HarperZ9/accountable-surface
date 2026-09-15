"""Scope normalization and matching for read-authority grants."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import unquote, urlsplit


def describe_fs_scope(root: str | Path, target: str | Path) -> tuple[str, str, str]:
    root_path, target_path, rel = _resolve_target(root, target)
    return f"file://{target_path}", _path_key(root_path), _parts_key(rel)


def describe_web_scope(url: str) -> tuple[str, str]:
    return _web_parts(url)


def describe_api_scope(service: Any, target: str, path_shape: str, intent: str) -> tuple[str, str]:
    path = _api_path(service, target)
    if re.fullmatch(path_shape, path) is None:
        raise ValueError(f"target {target!r} does not match intent {intent!r}")
    return service.origin + path, path


def scope_matches(scope: Any, request: Any) -> bool:
    if not isinstance(scope, dict) or scope.get("observation_kind") != request.observation_kind:
        return False
    phases = scope.get("phases") if "phases" in scope else ["direct"]
    if not isinstance(phases, list) or request.phase not in phases:
        return False
    target_scope = scope.get("target_scope") or {}
    if request.observation_kind == "fs.bytes":
        return _fs_scope_matches(target_scope, request.target_scope)
    if request.observation_kind == "web.document":
        return _web_scope_matches(target_scope, request.target_scope)
    if request.observation_kind == "api.resource":
        return _api_scope_matches(target_scope, request.target_scope)
    if request.observation_kind.startswith("journal."):
        return _journal_scope_matches(target_scope, request.target_scope)
    return False


def _resolve_target(root: str | Path, target: str | Path) -> tuple[Path, Path, PurePath]:
    raw = str(target)
    if any(part == ".." for part in PurePath(raw).parts):
        raise ValueError("dotdot filesystem target is not readable")
    target_path = Path(raw)
    if target_path.drive and not target_path.is_absolute():
        raise ValueError("drive-relative filesystem target is not readable")
    root_path = Path(root).resolve(strict=False)
    absolute = target_path if target_path.is_absolute() else root_path / target_path
    target_path = absolute.resolve(strict=False)
    try:
        rel = target_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("filesystem target is outside the registered root") from exc
    return root_path, target_path, rel


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _parts_key(path: PurePath) -> str:
    return "/".join(os.path.normcase(part) for part in path.parts)


def _fs_scope_matches(scope: Any, wanted: dict[str, Any]) -> bool:
    if not isinstance(scope, dict) or scope.get("kind") != "fs":
        return False
    if _path_key(Path(str(scope.get("root", "")))) != wanted.get("root"):
        return False
    paths = scope.get("paths") or []
    return isinstance(paths, list) and any(_path_pattern_matches(p, wanted.get("path", "")) for p in paths)


def _path_pattern_matches(pattern: Any, rel: str) -> bool:
    if not isinstance(pattern, str) or pattern == "":
        return False
    pattern = pattern.replace("\\", "/").strip("/")
    if any(ch in pattern for ch in "?[]") or any(part == ".." for part in pattern.split("/")):
        return False
    if pattern == "**":
        return True
    if "*" in pattern[:-3] or ("*" in pattern and not pattern.endswith("/**")):
        return False
    if pattern.endswith("/**"):
        prefix = _norm_segments(pattern[:-3])
        wanted = _norm_segments(rel)
        return wanted[:len(prefix)] == prefix
    return _norm_segments(pattern) == _norm_segments(rel)


def _norm_segments(path: str) -> list[str]:
    return [os.path.normcase(part) for part in path.split("/") if part]


def _web_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("web read requires http(s) URL without userinfo")
    path = parsed.path or "/"
    if any(unquote(part) == ".." for part in path.split("/")):
        raise ValueError("web read path contains dotdot")
    port = parsed.port
    default = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    origin = f"{parsed.scheme}://{parsed.hostname.lower()}" + ("" if port is None or default else f":{port}")
    return origin, path


def _web_scope_matches(scope: Any, wanted: dict[str, Any]) -> bool:
    if not isinstance(scope, dict) or scope.get("kind") != "web":
        return False
    allowed_origins = set()
    for origin in _strings(scope.get("origins")) or _strings([scope.get("origin")]):
        try:
            allowed_origins.add(_web_parts(origin)[0])
        except ValueError:
            continue
    paths = _strings(scope.get("paths"))
    if not paths:
        return False
    return wanted.get("origin") in allowed_origins and any(_slash_pattern_matches(p, wanted.get("path", "/")) for p in paths)


def _slash_pattern_matches(pattern: Any, path: str) -> bool:
    if not isinstance(pattern, str) or not pattern.startswith("/"):
        return False
    return _path_pattern_matches(pattern.strip("/"), path.strip("/"))


def _api_path(service: Any, target: str) -> str:
    if target.startswith(service.origin + "/"):
        return target[len(service.origin):]
    if target.startswith("http://") or target.startswith("https://"):
        raise ValueError(f"api target is outside {service.origin}")
    return target if target.startswith("/") else "/" + target


def _api_scope_matches(scope: Any, wanted: dict[str, Any]) -> bool:
    if not isinstance(scope, dict) or scope.get("kind") != "api":
        return False
    origins = _strings(scope.get("origins")) or _strings([scope.get("origin")])
    intents = _strings(scope.get("intents")) or _strings([scope.get("intent")])
    paths = _strings(scope.get("paths")) or _strings([scope.get("path_shape")])
    return (
        scope.get("service") == wanted.get("service") and wanted.get("origin") in origins
        and wanted.get("intent") in intents
        and any(p == wanted.get("path_shape") or _slash_pattern_matches(p, wanted.get("path", "/")) for p in paths)
    )


def _journal_scope_matches(scope: Any, wanted: dict[str, Any]) -> bool:
    return isinstance(scope, dict) and scope.get("kind") == "journal" and scope.get("visibility") == wanted.get("visibility")


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
