"""The Accountable Surface (Phase 2 spike) — the live seam where a model
perceives-and-acts under witness + gate.

A standalone composition of EXISTING, audited parts, proving the keystone before
any surgery on released ORCA 1.0.0:

  * perception — coherence-membrane organs (here, WebDocumentOrgan) emit
    witnessed Observations; nothing reaches the model un-witnessed.
  * action     — every proposed action is routed through proof-surface's
    pre-execution gate (allow / deny / needs-human) via the membrane's
    build_gate_request/decide bridge. The surface NEVER executes; it returns the
    gate's advisory decision for the operator/runtime to enforce.
  * memory     — every perception and every decision is journaled.

The surface holds no authority. It perceives, it asks the gate, it records — the
operational form of "awareness is not authority" and "machines learning to hold
themselves accountable."

Run/imports require coherence_membrane and proof_surface on the path, e.g.:
  PYTHONPATH="<coherence-membrane>/src;<proof-surface>/src" python -m pytest ...
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coherence_membrane.membrane import build_gate_request, decide
from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex
from coherence_membrane.organs.web import WebDocumentOrgan


@dataclass(frozen=True)
class JournalEntry:
    kind: str  # "perception" | "decision"
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "summary": self.summary, "detail": self.detail}

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "JournalEntry":
        return cls(
            kind=record["kind"],
            summary=record["summary"],
            detail=record.get("detail", {}),
        )


@dataclass(frozen=True)
class ActionOutcome:
    """The gate's advisory result for a proposed action. `executed` is ALWAYS
    False — the surface reports a decision; it never acts on it."""

    decision: str  # "allow" | "deny" | "needs-human"
    reasons: list[str]
    checks: dict[str, str]
    executed: bool
    request: dict[str, Any]


class AccountableSurface:
    """Perceive through witnessed organs; gate every action; journal everything.
    Never executes."""

    def __init__(self, journal_path: str | Path | None = None) -> None:
        self._web = WebDocumentOrgan()
        self.journal: list[JournalEntry] = []
        self._journal_path: Path | None = Path(journal_path) if journal_path else None
        self.replay_errors: int = 0
        if self._journal_path is not None:
            self._replay()

    def _replay(self) -> None:
        """Load an existing append-only journal into memory. Blank lines are
        skipped; a line that does not parse is counted in `replay_errors` (a
        tamper/corruption signal) and never silently dropped. An absent file is
        an empty journal, not an error."""
        path = self._journal_path
        if path is None or not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                self.journal.append(JournalEntry.from_dict(json.loads(stripped)))
            except (ValueError, KeyError, TypeError):
                self.replay_errors += 1

    def _record(self, entry: JournalEntry) -> None:
        """Append an entry to the in-memory journal and, when persisting, to the
        append-only JSONL file (one compact JSON object per line). The surface
        only ever appends — it never rewrites or truncates the record."""
        self.journal.append(entry)
        if self._journal_path is not None:
            line = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":"))
            with self._journal_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def perceive(self, subject: Any) -> Observation:
        """Perceive a subject (URL, bytes, or path) into a witnessed Observation
        and record it in the journal."""
        observation = self._web.observe(subject)[0]
        self._record(
            JournalEntry(
                kind="perception",
                summary=f"{observation.organ}: {observation.summary}",
                detail={
                    "subject": observation.subject,
                    "status": observation.status.value,
                    "digest": observation.provenance.digest,
                    "title": observation.data.get("title"),
                    "link_count": observation.data.get("link_count"),
                },
            )
        )
        return observation

    def propose(
        self,
        *,
        action_kind: str,
        target: str,
        authorization: dict[str, Any],
        observation: Observation | None = None,
        expected_digest: str | None = None,
        budget: dict[str, Any] | None = None,
        estimated_cost: dict[str, Any] | None = None,
    ) -> ActionOutcome:
        """Route a proposed action through the write-gate. Returns the advisory
        decision; the surface does not execute it."""
        request = build_gate_request(
            action_kind=action_kind,
            target=target,
            authorization=authorization,
            observation=observation,
            expected_digest=expected_digest,
            budget=budget,
            estimated_cost=estimated_cost,
        )
        gate = decide(request)
        # decide() returns proof-surface's GateDecision, or a fail-closed dict if
        # proof-surface is not installed. Read both shapes without assuming.
        decision = getattr(gate, "decision", None)
        if decision is None and isinstance(gate, dict):
            decision = gate.get("decision", "needs-human")
        reasons = getattr(gate, "reasons", None)
        if reasons is None and isinstance(gate, dict):
            reasons = gate.get("reasons", [])
        checks = getattr(gate, "checks", None)
        if checks is None and isinstance(gate, dict):
            checks = gate.get("checks", {})

        outcome = ActionOutcome(
            decision=str(decision),
            reasons=list(reasons or []),
            checks=dict(checks or {}),
            executed=False,
            request=request,
        )
        self._record(
            JournalEntry(
                kind="decision",
                summary=f"{action_kind} -> {target}: {outcome.decision}",
                detail={
                    "decision": outcome.decision,
                    "reasons": outcome.reasons,
                    "checks": outcome.checks,
                },
            )
        )
        return outcome

    def interocept(self) -> Observation:
        """Perceive the surface's OWN session — a witnessed, tamper-evident view
        of what it has perceived and what the gate decided. A pure read: it does
        not append to the journal, grants no authority, and its journal_digest
        re-derives, so the self-report cannot silently drift."""
        entries = [{"kind": e.kind, "summary": e.summary} for e in self.journal]
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        perceptions = 0
        decision_counts: dict[str, int] = {}
        for entry in self.journal:
            if entry.kind == "perception":
                perceptions += 1
            elif entry.kind == "decision":
                decision = str(entry.detail.get("decision", "?"))
                decision_counts[decision] = decision_counts.get(decision, 0) + 1
        decisions = sum(decision_counts.values())
        return Observation(
            organ="interoception",
            subject="self://session",
            summary=f"self: {perceptions} perceptions, {decisions} decisions",
            status=Status.PASS,
            provenance=Provenance.witness_bytes("self://session", payload, "high"),
            data={
                "perceptions": perceptions,
                "decisions": decisions,
                "decision_counts": decision_counts,
                "pending_needs_human": decision_counts.get("needs-human", 0),
                "journal_digest": "sha256:" + sha256_hex(payload),
                "entries": entries,
            },
        )
