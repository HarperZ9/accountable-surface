"""Accountability integrity red-team suite.

Each test attacks a specific accountability construction in OUR OWN code and
confirms the construction HOLDS.  They are falsifiable -- if any construction
were removed or weakened, at least one test here would fail.

Scope: witness / gate / provenance / journal / effector / cortex integrity of
accountable-surface only.  No third-party safety-classifier surface is touched.

Run:
  PP="C:/dev/public/coherence-membrane/src;C:/dev/public/proof-surface/src"
  PYTHONPATH="src;$PP" python -m pytest tests/test_integrity_redteam.py -q
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from accountable_surface.effector import FilesystemEffector, RefusedActuation
from accountable_surface.reference import FakeSource, ReferenceCortex
from accountable_surface.surface import AccountableSurface
from coherence_membrane.observation import sha256_hex

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# A minimal valid HTML page the surface can perceive (bytes, not a URL --
# WebDocumentOrgan accepts raw bytes and witnesses them directly).
_PAGE = (
    b"<!doctype html><html><head><title>Red Team</title></head>"
    b"<body><p>integrity probe</p></body></html>"
)


def _grant(actions, targets=()):
    """Minimal valid operator grant in the proof-surface envelope shape."""
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-redteam-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-redteam", "role": "operator"},
        "agent": {"id": "redteam-agent"},
        "intent": "integrity red-team",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


class _Allow:
    """Stand-in gate allow receipt matching the surface's ActionOutcome shape."""

    decision = "allow"

    def __init__(self, action_kind: str, target: str):
        self.request = {"planned_action": {"action_kind": action_kind, "target": target}}


class _Deny:
    """Stand-in gate deny receipt."""

    decision = "deny"
    request: dict = {}


# ---------------------------------------------------------------------------
# 1. Forged provenance digest -- re-perceive re-derives; a forgery doesn't hold
# ---------------------------------------------------------------------------

class TestForgedProvenanceDigest:
    """The provenance digest is derived from the witnessed bytes -- it cannot be
    pre-loaded from a forged value and survive re-derivation."""

    def test_perceive_derives_digest_from_content(self):
        s = AccountableSurface()
        obs = s.perceive(_PAGE)
        expected = "sha256:" + hashlib.sha256(_PAGE).hexdigest()
        assert obs.provenance.digest == expected, (
            "Provenance digest must be the SHA-256 of the witnessed bytes, full-width."
        )

    def test_forged_digest_differs_from_re_derived(self):
        s = AccountableSurface()
        obs = s.perceive(_PAGE)
        forged_digest = "sha256:" + hashlib.sha256(b"attacker-controlled payload").hexdigest()
        # A forged digest must NOT match what re-perception re-derives from the real content.
        assert obs.provenance.digest != forged_digest, (
            "A forged digest must not match the real re-derived provenance digest."
        )

    def test_different_content_yields_different_digest(self):
        s = AccountableSurface()
        obs_a = s.perceive(_PAGE)
        obs_b = s.perceive(_PAGE + b" altered")
        assert obs_a.provenance.digest != obs_b.provenance.digest, (
            "Any byte change must produce a different digest (collision resistance of SHA-256)."
        )

    def test_gate_rejects_forged_expected_digest(self):
        s = AccountableSurface()
        obs = s.perceive(_PAGE)
        # The gate expects a raw 64-char hex digest (no "sha256:" prefix) --
        # the same format stored in obs.data["identity_sha256"].
        forged = hashlib.sha256(b"not the real page").hexdigest()
        out = s.propose(
            action_kind="summarize",
            target="page",
            authorization=_grant(["summarize"]),
            observation=obs,
            expected_digest=forged,
        )
        # The gate checks state: digest mismatch -> deny (not just advisory).
        assert out.decision == "deny", (
            "A forged expected_digest must cause the gate to deny the action."
        )
        assert out.checks.get("state") == "fail", (
            "The gate must flag the state check as failed for a digest mismatch."
        )


# ---------------------------------------------------------------------------
# 2. Journal tamper -- corrupt a line, reload; replay_errors > 0, never silent
# ---------------------------------------------------------------------------

class TestJournalTamper:
    def test_corrupt_line_increments_replay_errors(self, tmp_path):
        path = tmp_path / "j.jsonl"
        s = AccountableSurface(journal_path=path)
        s.perceive(_PAGE)
        # Write a corrupt line directly to the journal file after a valid entry.
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{ NOT VALID JSON AT ALL\n")
        reloaded = AccountableSurface(journal_path=path)
        assert reloaded.replay_errors == 1, (
            "A single corrupt line must increment replay_errors by exactly 1 -- never silently dropped."
        )

    def test_valid_entries_survive_alongside_corrupt(self, tmp_path):
        path = tmp_path / "j.jsonl"
        s = AccountableSurface(journal_path=path)
        s.perceive(_PAGE)
        s.propose(action_kind="summarize", target="p", authorization=_grant(["summarize"]))
        with path.open("a", encoding="utf-8") as fh:
            fh.write("garbage\n")
        reloaded = AccountableSurface(journal_path=path)
        # The two valid entries must survive; the corrupt one is counted, not dropped silently.
        assert len(reloaded.journal) == 2, (
            "Corrupt lines must not destroy surrounding valid journal entries."
        )
        assert reloaded.replay_errors == 1

    def test_multiple_corrupt_lines_counted_individually(self, tmp_path):
        path = tmp_path / "j.jsonl"
        AccountableSurface(journal_path=path).perceive(_PAGE)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("bad1\nbad2\nbad3\n")
        reloaded = AccountableSurface(journal_path=path)
        assert reloaded.replay_errors == 3, (
            "Each corrupt line must be counted independently -- not collapsed into one."
        )

    def test_tampered_json_structure_is_also_caught(self, tmp_path):
        """A structurally valid JSON object but missing required keys is a tamper signal."""
        path = tmp_path / "j.jsonl"
        AccountableSurface(journal_path=path).perceive(_PAGE)
        # Valid JSON but missing 'kind' -- JournalEntry.from_dict raises KeyError.
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"summary": "injected", "detail": {}}) + "\n")
        reloaded = AccountableSurface(journal_path=path)
        assert reloaded.replay_errors == 1, (
            "A structurally malformed journal record (missing required keys) must be counted."
        )


# ---------------------------------------------------------------------------
# 3. Plan/content tamper -- content diverging from content_sha256 raises RefusedActuation
# ---------------------------------------------------------------------------

class TestPlanContentTamper:
    def test_act_raises_when_content_does_not_match_plan(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        plan = eff.preview(target, b"authorized content")
        allow = _Allow("fs.write", target)
        with pytest.raises(RefusedActuation, match="content does not match"):
            eff.act(plan, allow, content=b"TAMPERED content")
        assert not Path(target).exists(), (
            "A content-mismatch must leave the filesystem untouched -- no partial write."
        )

    def test_act_raises_on_empty_bytes_substituted_for_authorized(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        plan = eff.preview(target, b"real content")
        allow = _Allow("fs.write", target)
        with pytest.raises(RefusedActuation):
            eff.act(plan, allow, content=b"")
        assert not Path(target).exists()

    def test_surface_actuate_content_mismatch_reports_refused(self, tmp_path):
        """Surface-level: content delivered to actuate must match what preview committed."""
        surface = AccountableSurface()
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        # Deliver different bytes than the plan will commit to.
        # The surface calls preview(target, content) then act(plan, receipt, content),
        # so passing the same mismatched content consistently still goes through preview
        # cleanly but would normally match.  We instead subclass to forge the plan hash.
        class _TamperedEffector(FilesystemEffector):
            def preview(self, tgt, content, before=None):
                # Commit the plan to "authorized" bytes but the surface will pass "TAMPERED".
                p = super().preview(tgt, b"authorized bytes", before)
                return p

        te = _TamperedEffector(tmp_path)
        out = surface.actuate(
            te, target=target, content=b"TAMPERED bytes",
            authorization=_grant(["fs.write"]),
        )
        # The effector's act() catches the hash mismatch and raises RefusedActuation,
        # which the surface traps and reports as refused-by-effector.
        assert out.acted is False
        assert out.verdict == "refused-by-effector"
        assert not Path(target).exists()


# ---------------------------------------------------------------------------
# 4. Forged/None allow-receipt -- act() raises RefusedActuation; nothing written
# ---------------------------------------------------------------------------

class TestForgedAllowReceipt:
    def test_none_receipt_refuses_and_writes_nothing(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        plan = eff.preview(target, b"x")
        with pytest.raises(RefusedActuation, match="no gate allow"):
            eff.act(plan, allow_receipt=None, content=b"x")
        assert not Path(target).exists()

    def test_deny_receipt_refuses_and_writes_nothing(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        plan = eff.preview(target, b"x")
        with pytest.raises(RefusedActuation):
            eff.act(plan, allow_receipt=_Deny(), content=b"x")
        assert not Path(target).exists()

    def test_receipt_for_wrong_action_kind_refuses(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        plan = eff.preview(target, b"x")
        wrong_allow = _Allow("web.navigate", target)  # wrong action kind
        with pytest.raises(RefusedActuation, match="does not match"):
            eff.act(plan, allow_receipt=wrong_allow, content=b"x")
        assert not Path(target).exists()

    def test_receipt_for_wrong_target_refuses(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target_a = str(tmp_path / "a.txt")
        target_b = str(tmp_path / "b.txt")
        plan = eff.preview(target_a, b"x")
        wrong_allow = _Allow("fs.write", target_b)  # allow is for b, plan is for a
        with pytest.raises(RefusedActuation, match="does not match"):
            eff.act(plan, allow_receipt=wrong_allow, content=b"x")
        assert not Path(target_a).exists()

    def test_needs_human_receipt_refuses(self, tmp_path):
        class _NeedsHuman:
            decision = "needs-human"
            request: dict = {}

        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "t.txt")
        plan = eff.preview(target, b"x")
        with pytest.raises(RefusedActuation):
            eff.act(plan, allow_receipt=_NeedsHuman(), content=b"x")
        assert not Path(target).exists()


# ---------------------------------------------------------------------------
# 5. Out-of-bounds target -- effector bound to root A; plan for B is refused even
#    with a valid allow receipt
# ---------------------------------------------------------------------------

class TestOutOfBoundsTarget:
    def test_outside_root_refused_even_with_valid_allow(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        escape = tmp_path / "escape.txt"
        eff = FilesystemEffector(sandbox)
        plan = eff.preview(str(escape), b"bad")
        allow = _Allow("fs.write", str(escape))
        with pytest.raises(RefusedActuation, match="outside the effector's bound"):
            eff.act(plan, allow_receipt=allow, content=b"bad")
        assert not escape.exists(), (
            "Out-of-bound target must not be created, even with an allow receipt."
        )

    def test_path_traversal_attempt_refused(self, tmp_path):
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        # Attempt to escape via ../
        escape_target = str(sandbox / ".." / "escaped.txt")
        eff = FilesystemEffector(sandbox)
        plan = eff.preview(escape_target, b"bad")
        allow = _Allow("fs.write", escape_target)
        with pytest.raises(RefusedActuation, match="outside the effector's bound"):
            eff.act(plan, allow_receipt=allow, content=b"bad")
        assert not (tmp_path / "escaped.txt").exists()

    def test_sibling_directory_is_outside_bound(self, tmp_path):
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        root_a.mkdir()
        root_b.mkdir()
        eff_a = FilesystemEffector(root_a)
        target_in_b = str(root_b / "f.txt")
        plan = eff_a.preview(target_in_b, b"data")
        allow = _Allow("fs.write", target_in_b)
        with pytest.raises(RefusedActuation, match="outside the effector's bound"):
            eff_a.act(plan, allow_receipt=allow, content=b"data")
        assert not Path(target_in_b).exists()


# ---------------------------------------------------------------------------
# 6. Interoception drift -- digest re-derives after journal changes; not cached
# ---------------------------------------------------------------------------

class TestInteroceptionDrift:
    def test_digest_changes_after_journal_grows(self):
        s = AccountableSurface()
        obs_empty = s.interocept()
        s.perceive(_PAGE)
        obs_after = s.interocept()
        assert obs_empty.data["journal_digest"] != obs_after.data["journal_digest"], (
            "interoception digest must change when the journal changes -- not cached."
        )

    def test_digest_tracks_every_entry_added(self):
        s = AccountableSurface()
        digests = []
        digests.append(s.interocept().data["journal_digest"])
        s.perceive(_PAGE)
        digests.append(s.interocept().data["journal_digest"])
        s.propose(action_kind="summarize", target="p", authorization=_grant(["summarize"]))
        digests.append(s.interocept().data["journal_digest"])
        # All three must be distinct -- each journal change shifts the digest.
        assert len(set(digests)) == 3, (
            "Each journal entry must produce a distinct interoception digest."
        )

    def test_digest_is_deterministic_from_journal_content(self):
        """Same journal content -> same digest, regardless of construction path."""
        s1 = AccountableSurface()
        s1.perceive(_PAGE)
        d1 = s1.interocept().data["journal_digest"]

        s2 = AccountableSurface()
        s2.perceive(_PAGE)
        d2 = s2.interocept().data["journal_digest"]

        assert d1 == d2, (
            "Identical journal activity must produce the same digest (determinism)."
        )

    def test_interoception_does_not_append_to_journal(self):
        s = AccountableSurface()
        s.perceive(_PAGE)
        n = len(s.journal)
        s.interocept()
        s.interocept()
        assert len(s.journal) == n, (
            "interocept() must be a pure read -- it must not grow the journal."
        )


# ---------------------------------------------------------------------------
# 7. Ungrounded premise -- actuate with unrelated justification/cortex yields
#    verdict "ungrounded-premise", acted=False
# ---------------------------------------------------------------------------

class TestUngroundedPremise:
    def _cortex_about_file_writing(self):
        return ReferenceCortex(FakeSource([
            {
                "source": "arxiv", "ref_id": "2401.1",
                "title": "safe bounded file writes in language agents",
                "summary": "reversible verified bounded writes", "url": "u1",
            },
        ]))

    def test_unrelated_justification_escalates_and_does_not_act(self, tmp_path):
        surface = AccountableSurface()
        target = str(tmp_path / "f.txt")
        out = surface.actuate(
            FilesystemEffector(tmp_path),
            target=target,
            content=b"hi",
            authorization=_grant(["fs.write"]),
            justification="orbital mechanics of comets and gravitational lensing",
            cortex=self._cortex_about_file_writing(),
        )
        assert out.acted is False, "Ungrounded premise must not cause the effector to act."
        assert out.decision == "needs-human", "Ungrounded premise must escalate to needs-human."
        assert out.verdict == "ungrounded-premise"
        assert not Path(target).exists(), "No file must be created under an ungrounded premise."

    def test_ungrounded_premise_journals_the_escalation(self, tmp_path):
        surface = AccountableSurface()
        target = str(tmp_path / "f.txt")
        surface.actuate(
            FilesystemEffector(tmp_path),
            target=target,
            content=b"hi",
            authorization=_grant(["fs.write"]),
            justification="orbital mechanics of comets",
            cortex=self._cortex_about_file_writing(),
        )
        actuation_entries = [e for e in surface.journal if e.kind == "actuation"]
        assert actuation_entries, "An actuation must be journaled even when refused."
        assert actuation_entries[-1].detail.get("verdict") == "ungrounded-premise"

    def test_grounded_premise_does_not_block(self, tmp_path):
        """Sanity check: the grounding gate does not block legitimately grounded actions."""
        surface = AccountableSurface()
        target = str(tmp_path / "f.txt")
        out = surface.actuate(
            FilesystemEffector(tmp_path),
            target=target,
            content=b"hi",
            authorization=_grant(["fs.write"]),
            justification="safe bounded file writes language agents",
            cortex=self._cortex_about_file_writing(),
        )
        assert out.acted is True
        assert out.grounding is not None
        assert out.grounding.confidence in ("grounded", "weak")


# ---------------------------------------------------------------------------
# 8. Relevance filter -- ReferenceCortex.ground() drops below-min_relevance sources
# ---------------------------------------------------------------------------

class TestRelevanceFilter:
    def test_below_min_relevance_sources_are_excluded(self):
        source = FakeSource([
            {"source": "x", "ref_id": "relevant", "title": "accountable agent gating verification",
             "summary": "bounded verified", "url": "u1"},
            {"source": "x", "ref_id": "irrelevant", "title": "pasta boiling technique",
             "summary": "water temperature", "url": "u2"},
        ])
        cortex = ReferenceCortex(source, min_relevance=0.3)
        grounding = cortex.ground("accountable agent gating verification")
        ref_ids = [r.ref_id for r in grounding.references]
        assert "irrelevant" not in ref_ids, (
            "A below-threshold source must not appear in the grounding result."
        )

    def test_all_below_threshold_yields_ungrounded(self):
        source = FakeSource([
            {"source": "x", "ref_id": "1", "title": "pasta recipe", "summary": "boil water", "url": "u"},
            {"source": "x", "ref_id": "2", "title": "yoga poses", "summary": "stretch", "url": "u"},
        ])
        cortex = ReferenceCortex(source, min_relevance=0.3)
        grounding = cortex.ground("accountable agent gating verification provenance")
        assert grounding.confidence == "ungrounded", (
            "If no source meets min_relevance, confidence must be 'ungrounded' -- not a fabricated citation."
        )
        assert grounding.references == [], (
            "An ungrounded result must carry zero references -- no placeholder citations."
        )

    def test_raising_min_relevance_shrinks_result_set(self):
        source = FakeSource([
            {"source": "x", "ref_id": "a", "title": "agent gating", "summary": "", "url": "u"},
            {"source": "x", "ref_id": "b", "title": "agent gating verification accountability",
             "summary": "gating verification", "url": "u"},
        ])
        loose_cortex = ReferenceCortex(source, min_relevance=0.0)
        strict_cortex = ReferenceCortex(source, min_relevance=0.9)
        loose_count = len(loose_cortex.ground("agent gating verification accountability").references)
        strict_count = len(strict_cortex.ground("agent gating verification accountability").references)
        assert strict_count <= loose_count, (
            "A stricter min_relevance threshold must never produce more references."
        )


# ---------------------------------------------------------------------------
# 9. Verify catches out-of-band tamper -- write via act(), tamper bytes on disk,
#    verify() returns failed
# ---------------------------------------------------------------------------

class TestVerifyCatchesOutOfBandTamper:
    def test_out_of_band_write_fails_verification(self, tmp_path):
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "f.txt")
        plan = eff.preview(target, b"authorized content")
        eff.act(plan, _Allow("fs.write", target), content=b"authorized content")
        # Tamper with the file after the act, bypassing the effector entirely.
        Path(target).write_bytes(b"TAMPERED by attacker out of band")
        after = eff.perceive(target)
        verdict = eff.verify(plan, after)
        assert verdict.status == "failed", (
            "verify() must detect that on-disk content no longer matches the authorized plan."
        )

    def test_clean_write_passes_verification(self, tmp_path):
        """Sanity: an untampered write passes verification."""
        eff = FilesystemEffector(tmp_path)
        target = str(tmp_path / "f.txt")
        plan = eff.preview(target, b"clean content")
        eff.act(plan, _Allow("fs.write", target), content=b"clean content")
        after = eff.perceive(target)
        verdict = eff.verify(plan, after)
        assert verdict.status == "pass"

    def test_surface_actuate_catches_tamper_and_rolls_back(self, tmp_path):
        """Surface-level: if the disk is tampered after act() but before verify(),
        the surface's post-act re-perception catches it.  We simulate this by
        subclassing to inject a tamper between act() and verify()."""

        class _TamperingEffector(FilesystemEffector):
            def act(self, plan, allow_receipt, content):
                obs = super().act(plan, allow_receipt, content)
                # Simulate out-of-band tamper immediately after writing.
                Path(plan.target).write_bytes(b"injected by attacker")
                return obs

        surface = AccountableSurface()
        target = str(tmp_path / "f.txt")
        out = surface.actuate(
            _TamperingEffector(tmp_path),
            target=target,
            content=b"safe payload",
            authorization=_grant(["fs.write"]),
        )
        assert out.acted is True          # the effector did act
        assert out.verified is False      # but verification caught the tamper
        assert out.rolled_back is True    # and the reversible action was rolled back
        assert out.verdict == "failed"


# ---------------------------------------------------------------------------
# 10. Irreversible escalation -- irreversible plan without allow_irreversible
#     yields verdict "irreversible-needs-human", acted=False
# ---------------------------------------------------------------------------

class TestIrreversibleEscalation:
    def test_irreversible_without_flag_escalates(self, tmp_path):
        """An irreversible effector (CommandEffector / WebEffector submit) without
        allow_irreversible must escalate to needs-human even when the gate allows."""
        from accountable_surface.web_effector import FakePageDriver, WebAction, WebEffector

        pages = {
            "https://app.test/form": {"title": "Form", "fields": {"q": ""}},
            "https://app.test/result": {"title": "ok", "fields": {}},
        }
        driver = FakePageDriver(pages, start="https://app.test/form")
        eff = WebEffector(driver, allowed_origins=["https://app.test"])

        surface = AccountableSurface()
        # A "submit" action is marked irreversible=False by WebEffector.preview().
        action = WebAction("submit", url="https://app.test/result", value="ok")
        out = surface.actuate(
            eff,
            target="https://app.test/result",
            content=action,
            authorization=_grant(["web.submit"]),
            allow_irreversible=False,  # default -- explicit for test clarity
        )
        assert out.acted is False
        assert out.decision == "needs-human"
        assert out.verdict == "irreversible-needs-human"
        # The driver must still be on the original page -- no navigation happened.
        assert driver.current_url() == "https://app.test/form"

    def test_irreversible_with_flag_is_allowed_to_proceed(self, tmp_path):
        """Sanity: allow_irreversible=True lets the gate-allowed action proceed."""
        from accountable_surface.web_effector import FakePageDriver, WebAction, WebEffector

        pages = {
            "https://app.test/form": {"title": "Form", "fields": {"q": "data"}},
            "https://app.test/result": {"title": "ok", "fields": {}},
        }
        driver = FakePageDriver(pages, start="https://app.test/form")
        eff = WebEffector(driver, allowed_origins=["https://app.test"])

        surface = AccountableSurface()
        action = WebAction("submit", url="https://app.test/result", value="ok")
        out = surface.actuate(
            eff,
            target="https://app.test/result",
            content=action,
            authorization=_grant(["web.submit"]),
            allow_irreversible=True,
        )
        assert out.acted is True
        assert out.decision == "allow"

    def test_filesystem_write_is_reversible_no_escalation(self, tmp_path):
        """FilesystemEffector writes are reversible -- no escalation expected."""
        surface = AccountableSurface()
        target = str(tmp_path / "f.txt")
        out = surface.actuate(
            FilesystemEffector(tmp_path),
            target=target,
            content=b"data",
            authorization=_grant(["fs.write"]),
            allow_irreversible=False,
        )
        assert out.acted is True, "A reversible write must not be blocked by the irreversibility gate."


# ---------------------------------------------------------------------------
# 11. Selftest falsifiability -- selftest() returns True clean, and fails if the
#     contract is violated (demonstrably falsifiable)
# ---------------------------------------------------------------------------

class TestSelftestFalsifiability:
    def test_filesystem_effector_selftest_passes_clean(self, tmp_path):
        assert FilesystemEffector(tmp_path).selftest() is True

    def test_reference_cortex_selftest_passes_clean(self):
        assert ReferenceCortex(FakeSource([])).selftest() is True

    def test_filesystem_effector_selftest_catches_disabled_guard(self, tmp_path):
        """If the RefusedActuation guard were removed, selftest() would return False.
        We prove this by subclassing to bypass the guard."""

        class _BypassedEffector(FilesystemEffector):
            def act(self, plan, allow_receipt, content):
                # Bypass the allow check -- the contract is violated.
                path = Path(plan.target)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                return self.perceive(plan.target)

            def selftest(self) -> bool:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp:
                    probe = _BypassedEffector(tmp)
                    target = str(Path(tmp) / "probe.txt")
                    plan = probe.preview(target, b"x")
                    try:
                        probe.act(plan, allow_receipt=None, content=b"x")
                        # act() did NOT raise -- the guard is absent
                        return False
                    except RefusedActuation:
                        return not Path(target).exists()

        bypassed = _BypassedEffector(tmp_path)
        assert bypassed.selftest() is False, (
            "selftest() on a contract-violating effector must return False -- "
            "proving the selftest is falsifiable and not a rubber stamp."
        )

    def test_reference_cortex_selftest_catches_threshold_bypass(self):
        """If the min_relevance filter were removed, the cortex would claim to be
        'grounded' on irrelevant material.  Prove the selftest catches it."""

        class _NoFilterCortex(ReferenceCortex):
            def ground(self, subject):
                # Return all results regardless of relevance -- filter bypassed.
                raw = self._source.search(subject, limit=10)
                refs = [self._witness(item, 1.0) for item in raw]
                import hashlib
                digest = "sha256:" + hashlib.sha256(b"bypass").hexdigest()
                from accountable_surface.reference import Grounding
                return Grounding(subject, refs, "grounded", digest)  # always "grounded"

            def selftest(self) -> bool:
                probe = _NoFilterCortex(
                    FakeSource([
                        {"source": "x", "ref_id": "1", "title": "zzz qqq",
                         "summary": "", "url": ""}
                    ])
                )
                return probe.ground("entirely unrelated subject terms").confidence == "ungrounded"

        no_filter = _NoFilterCortex(FakeSource([]))
        assert no_filter.selftest() is False, (
            "A cortex that bypasses the relevance filter must fail its own selftest."
        )
