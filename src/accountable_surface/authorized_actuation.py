"""Remote actuation path that consumes server-internal read authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from accountable_surface.bounds import bound_of
from accountable_surface.effector import RefusedActuation
from accountable_surface.read_authority import AuthorizedRead, ReadEnvelope, validate_authorized_read


def actuate_with_authorized_read(
    surface: Any,
    effector: Any,
    *,
    target: str,
    content: Any,
    authorization: dict[str, Any],
    authorized_before: AuthorizedRead,
    read_envelope: ReadEnvelope,
    expected_digest: str | None = None,
    justification: str | None = None,
    cortex: Any = None,
    confirm_authority: Callable[[], str | None] | None = None,
):
    """Run surface actuation using a pre-authorized before-read.

    The caller cannot supply this object. The MCP server builds it only after read
    grants match, then asks the authority store to reload once more before the
    effector mutates state.
    """
    before = authorized_before.observation
    read_audit = read_envelope.to_audit()
    plan = effector.preview(target, content, before)
    bound = bound_of(effector)
    expected_subject = _subject_for_plan(authorized_before.request.observation_kind, plan, target)
    reason = validate_authorized_read(authorized_before, read_envelope, subject=expected_subject)
    if reason is not None:
        return _refuse(surface, plan, before, bound, "read-authority-mismatch", reason, read_audit=read_audit)
    missing = read_envelope.missing_phases(
        authorized_before.request.observation_kind, expected_subject, _required_phases(plan, authorized_before)
    )
    if missing:
        return _refuse(surface, plan, before, bound, "read-authority-incomplete",
                       "missing read authority phase(s): " + ", ".join(missing), read_audit=read_audit)
    refusal, outcome, grounding = surface._preflight(
        plan, effector=effector, authorization=authorization, before=before, bound=bound,
        expected_digest=expected_digest, allow_irreversible=False, justification=justification, cortex=cortex,
        read_authority=read_audit,
    )
    if refusal is not None:
        return refusal
    if confirm_authority is not None:
        reason = confirm_authority()
        if reason is not None:
            return _refuse(
                surface, plan, before, bound, "authority-revoked-before-mutation", reason,
                grounding, read_audit=read_audit,
            )
    return _act_and_verify(surface, effector, plan, outcome, content, before, grounding, bound, read_audit)


def _refuse(surface, plan, before, bound, verdict: str, reason: str, grounding=None, read_audit=None):
    return surface._record_actuation(
        plan, acted=False, decision="deny", verdict=verdict, verified=False, rolled_back=False,
        reasons=[reason], before=before, after=None, grounding=grounding, bound=bound,
        read_authority=read_audit,
    )


def _act_and_verify(surface, effector, plan, outcome, content, before, grounding, bound, read_audit):
    try:
        effector.act(plan, outcome, content)
    except RefusedActuation as exc:
        return surface._record_actuation(
            plan, acted=False, decision=outcome.decision, verdict="refused-by-effector",
            verified=False, rolled_back=False, reasons=[str(exc)], before=before, after=None,
            grounding=grounding, bound=bound, read_authority=read_audit,
        )
    after = effector.perceive(plan.target)
    verdict = effector.verify(plan, after)
    verified = verdict.status == "pass"
    rolled_back = False
    if not verified and plan.reversible:
        effector.rollback(plan)
        rolled_back = True
        after = effector.perceive(plan.target)
    return surface._record_actuation(
        plan, acted=True, decision="allow", verdict=verdict.status, verified=verified,
        rolled_back=rolled_back, reasons=[verdict.detail] if verdict.detail else [],
        before=before, after=after, grounding=grounding, bound=bound,
        read_authority=read_audit,
    )


def _subject_for_plan(kind: str, plan: Any, target: str) -> str:
    if kind == "fs.bytes":
        return f"file://{Path(target).resolve(strict=False)}"
    return str(plan.target)


def _required_phases(plan: Any, authorized_before: AuthorizedRead) -> tuple[str, ...]:
    if authorized_before.request.observation_kind == "fs.bytes":
        return ("before", "backup", "after", "rollback")
    if getattr(plan, "reversible", False):
        return ("before", "after", "rollback")
    return ("before", "after")
