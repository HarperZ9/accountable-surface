"""State-precondition binding for actuation.

The coherence-membrane gate bridge reads ``identity_sha256`` from observations.
Actuation effectors expose their own state digests, so Accountable Surface maps
only explicit organ/field pairs into that bridge contract. Unknown observation
shapes fail closed when a caller supplies ``expected_digest``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from coherence_membrane.observation import Observation, Status


_RAW_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRECONDITION_IDENTITY_FIELDS = {
    "api-effector": "sha256",
    "browser-effector": "page_digest",
    "fs-effector": "sha256",
    "web-document": "identity_sha256",
}


@dataclass(frozen=True)
class BoundPrecondition:
    observation: Observation
    expected_digest: str


def bind_state_precondition(
    observation: Observation, expected_digest: Any,
) -> tuple[BoundPrecondition | None, str | None]:
    expected, reason = _raw_sha256(expected_digest, label="expected_digest")
    if expected is None:
        return None, reason
    identity, reason = _precondition_identity(observation)
    if identity is None:
        return None, reason
    return BoundPrecondition(_with_identity(observation, identity), expected), None


def _precondition_identity(observation: Observation) -> tuple[str | None, str | None]:
    field = _PRECONDITION_IDENTITY_FIELDS.get(observation.organ)
    if field is None:
        return None, f"{observation.organ!r} does not expose a supported precondition identity"
    if _status_value(observation) != Status.PASS.value:
        return None, f"{observation.organ!r} observation did not establish a pass-status identity"
    data = observation.data if isinstance(observation.data, dict) else {}
    return _raw_sha256(data.get(field), label=field)


def _raw_sha256(value: Any, *, label: str) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or _RAW_SHA256.fullmatch(value) is None:
        return None, f"{label} must be a raw 64-character lowercase sha256 hex digest"
    return value, None


def _status_value(observation: Observation) -> str:
    value = observation.status
    return str(getattr(value, "value", value))


def _with_identity(observation: Observation, identity: str) -> Observation:
    data = dict(observation.data)
    data["identity_sha256"] = identity
    return replace(observation, data=data)
