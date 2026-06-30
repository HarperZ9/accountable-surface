"""The efferent arm -- accountable actuation.

An Effector is the output-side analogue of a perception organ: **inert until
authorized**. It acts ONLY on a gate `allow` for the exact previewed plan, ONLY
within a construction-bounded scope, and emits witnessed Observations so the
surface can verify the effect by re-perceiving.

See project-docs/specs/2026-06-19-efferent-arm-actuation.md (design corpus).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex


@dataclass(frozen=True)
class Plan:
    """A witnessed description of an intended action -- produced BEFORE any effect,
    so it can be authorized and bound (the surface acts on THIS exact plan)."""

    action_kind: str
    target: str
    content_sha256: str
    reversible: bool
    existed_before: bool
    digest: str  # content-address of the plan (action_kind | target | content)


@dataclass(frozen=True)
class Verdict:
    status: str  # "pass" | "failed"
    detail: str = ""


class RefusedActuation(Exception):
    """An effector refuses to act: no gate allow, a receipt that does not match the
    plan, content that does not match the preview, or a target outside the bound."""


class FilesystemEffector:
    """Writes files within a construction-bounded root. Acts only on a gate allow
    for the exact plan; reversible (backs up prior content); witnesses every read
    and write so the surface can verify the effect."""

    name = "fs-effector"
    action_kind = "fs.write"

    def __init__(self, allowed_root: str | Path) -> None:
        self._root = Path(allowed_root).resolve()
        self._backups: dict[str, bytes | None] = {}

    # --- perception of the effector's own target type (fs state) -------------

    def perceive(self, target: str) -> Observation:
        """A witnessed read of the target's filesystem state."""
        path = Path(target)
        exists = path.is_file()
        payload = path.read_bytes() if exists else b""
        return Observation(
            organ=self.name,
            subject=f"file://{target}",
            summary=f"file {'present' if exists else 'absent'} ({len(payload)} bytes)",
            status=Status.PASS,
            provenance=Provenance.witness_bytes(f"file://{target}", payload, "high"),
            data={
                "exists": exists,
                "size": len(payload),
                "sha256": sha256_hex(payload) if exists else None,
            },
        )

    # --- the efferent contract ----------------------------------------------

    def preview(self, target: str, content: bytes, before: Observation | None = None) -> Plan:
        """Describe the intended write -- no side effect."""
        content_sha = sha256_hex(content)
        existed = bool(before.data.get("exists")) if before is not None else Path(target).is_file()
        digest = "sha256:" + sha256_hex(
            f"{self.action_kind}|{target}|{content_sha}".encode("utf-8")
        )
        return Plan(
            action_kind=self.action_kind,
            target=target,
            content_sha256=content_sha,
            reversible=True,
            existed_before=existed,
            digest=digest,
        )

    def act(self, plan: Plan, allow_receipt: Any, content: bytes) -> Observation:
        """Perform the write -- only with a valid allow receipt for THIS plan, only
        within the bound, and only if the content matches the preview. Backs up the
        prior content for rollback. Returns a witnessed post-action Observation."""
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow -- the effector will not act")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        if sha256_hex(content) != plan.content_sha256:
            raise RefusedActuation("content does not match the previewed (authorized) plan")
        if not self._within_root(plan.target):
            raise RefusedActuation(f"target is outside the effector's bound: {self._root}")
        path = Path(plan.target)
        self._backups[plan.target] = path.read_bytes() if path.is_file() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(path, content)
        return self.perceive(plan.target)

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        """Did the on-disk state match the authorized intent? (proprioception)."""
        if after.data.get("sha256") == plan.content_sha256:
            return Verdict("pass", "on-disk content matches the authorized plan")
        return Verdict("failed", "on-disk content does NOT match the authorized plan")

    def rollback(self, plan: Plan) -> Observation:
        """Restore the pre-action content (reversibility)."""
        if plan.target not in self._backups:
            raise RefusedActuation("no backup recorded for this target")
        prior = self._backups[plan.target]
        path = Path(plan.target)
        if prior is None:
            if path.is_file():
                path.unlink()
        else:
            path.write_bytes(prior)
        return self.perceive(plan.target)

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise and write nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            probe = FilesystemEffector(tmp)
            target = str(Path(tmp) / "probe.txt")
            plan = probe.preview(target, b"x")
            try:
                probe.act(plan, allow_receipt=None, content=b"x")
                return False  # acted without an allow -- contract violated
            except RefusedActuation:
                pass
            return not Path(target).exists()

    # --- internals -----------------------------------------------------------

    def _within_root(self, target: str) -> bool:
        try:
            Path(target).resolve().relative_to(self._root)
            return True
        except ValueError:
            return False

    def _write(self, path: Path, content: bytes) -> None:
        """The actual byte-write -- a hook subclasses (and tests) can override."""
        path.write_bytes(content)
