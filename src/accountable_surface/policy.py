"""The policy check before every action (S3): `decide` is a pure function.

    decide(step, before, grant, approval, paused, now) -> pass | confirm | refuse | stop

No clock (the time is an input), no environment, no network, no driver. Rules run
in a fixed order and every rule runs; the outcome is the strictest hit, ranked
pass < confirm < refuse < stop, so a rule can tighten the result and never loosen
it. Every hit is recorded with its rule, version, and reason.

    R1 hard exclusion      refuse   solver, stealth, fingerprint, user agent, proxy, ...
    R2 paused target       stop     an earlier challenge paused this origin
    R3 challenge on screen stop     and the pipeline pauses the target
    R4 secret field/value  refuse   the person types it
    R5 money movement      stop     the person acts
    R6 tier                refuse   the target's tier does not cover the action
    R7 irreversible        confirm  a person approves this exact step
    R8 content echo        confirm  the step came from agent-addressed page text
    R9 post-condition      refuse   missing, unsettleable, or the target does not resolve

The grant is read only in R6, after R1 to R5, and only for the target's tier. A
live approval (already checked by the approval store) turns a `confirm` into a
`pass` when it names this step digest and this before digest and has not
expired; it never lifts a refusal or a stop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from accountable_surface import plan as plan_mod
from accountable_surface import tiers
from accountable_surface.detectors import challenge, injection, irreversible, secrets

VERSION = "1"
RANK = {"pass": 0, "confirm": 1, "refuse": 2, "stop": 3}
TEXT_VERBS = frozenset({"fill", "set_value", "key", "write", "upload"})
EXCLUDED = (
    "captcha", "recaptcha", "hcaptcha", "turnstile", "solver", "solve", "stealth", "fingerprint",
    "useragent", "proxy", "humanize", "humanise", "jitter", "webdriver", "tokenharvest",
)
SCRIPT_EXCLUDED = ("webdriver", "useragent", "user-agent", "captcha", "turnstile", "fingerprint")


@dataclass(frozen=True)
class PolicyDecision:
    outcome: str
    rule_hits: list
    tier: dict | None
    approval: dict | None
    policy_digest: str
    inputs_digest: str
    pause: bool = False
    injection_flags: tuple = ()

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "rule_hits": self.rule_hits, "tier": self.tier,
                "approval": self.approval, "policy_digest": self.policy_digest,
                "inputs_digest": self.inputs_digest, "pause": self.pause,
                "injection_phrases": sorted({f.phrase for f in self.injection_flags})}


def policy_digest(config: dict | None = None) -> str:
    """Hash of the rule table, every detector lexicon, and the config."""
    return plan_mod.digest({
        "version": VERSION, "rank": RANK, "excluded": EXCLUDED, "script_excluded": SCRIPT_EXCLUDED,
        "challenge": challenge.lexicon(), "secrets": secrets.lexicon(),
        "irreversible": irreversible.lexicon(), "injection": injection.lexicon(),
        "tiers": {"required": tiers.REQUIRED, "flags": tiers.FLAGS}, "config": config or {},
    })


def target_key(step) -> str:
    """What a pause names: the origin, or the window's (title, image) pair."""
    window = step.target.get("window")
    if isinstance(window, dict):
        return f"window:{window.get('title', '')}|{window.get('image', '')}"
    return step.origin


def _hit(rule: str, outcome: str, reason: str) -> dict:
    return {"rule": rule, "version": VERSION, "outcome": outcome, "reason": reason}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _r1(step) -> list:
    names = [step.action_kind] + list(step.args)
    found = sorted({tok for n in names for tok in EXCLUDED if tok in _norm(n)})
    if step.action_kind.endswith(".evaluate"):
        script = str(step.args.get("value", "")).lower()
        found += sorted({tok for tok in SCRIPT_EXCLUDED if tok in script})
    return [_hit("R1.excluded", "refuse", f"names an excluded capability: {', '.join(found)}")] if found else []


def _r3(before) -> list:
    hits = challenge.scan(before)
    if not hits:
        return []
    markers = ", ".join(sorted({f"{h.where}:{h.marker}" for h in hits}))
    return [_hit("R3.challenge", "stop", f"a human check is on screen ({markers}); a person must handle it")]


def _r4(step, control) -> list:
    verb = step.action_kind.rsplit(".", 1)[-1]
    if verb not in TEXT_VERBS:
        return []
    hits = [_hit("R4.secret-field", "refuse", r) for r in secrets.field_markers(control)]
    shape = secrets.value_shape(str(step.args.get("value", "")))
    if shape:
        label = control.name if control is not None else "the target"
        hits.append(_hit("R4.value-shape", "refuse", f"the value for {label!r} has the shape of a {shape}"))
    if verb == "upload":
        why = secrets.upload_refusal(str(step.args.get("filename", "")), None)
        if why:
            hits.append(_hit("R4.upload", "refuse", f"upload refused: {why}"))
    return hits


def _tier_target(step) -> dict:
    window = step.target.get("window")
    return {"window": window} if isinstance(window, dict) else {"origin": step.origin}


def _r8(step, before, flags) -> list:
    verb = step.action_kind.rsplit(".", 1)[-1]
    fields = {"selector": (step.control or {}).get("name"), "value": step.args.get("value")}
    if verb == "navigate":
        fields["url"] = step.url
    return [_hit("R8.echo", "confirm", r) for r in injection.echo(fields, flags, page_origin=before.origin)]


def _r9(step, before, control) -> list:
    hits = []
    problem = plan_mod.post_condition_problem(step)
    if problem:
        hits.append(_hit("R9.post-condition", "refuse", problem))
    if step.control is not None and control is None:
        hits.append(_hit("R9.target-unresolved", "refuse",
                         "the named control is absent or ambiguous in the before evidence"))
    return hits


def _approval_ref(approval, step_digest: str, before_digest: str, now: str) -> dict | None:
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        return None
    if approval.get("step_digest") != step_digest or approval.get("before_digest") != before_digest:
        return None
    if str(approval.get("expires_at", "")) < now:
        return None
    return {k: approval.get(k) for k in ("approval_id", "record", "channel", "approver")}


def _content_rules(step, before) -> tuple[list, object]:
    """R3 to R5 and R7 to R9: the rules that read observed content."""
    control = before.find(step.control) if step.control is not None else None
    hits = _r3(before) + _r4(step, control)
    hits += [_hit("R5.funds", "stop", f"moves money ({r}); the person acts") for r in
             irreversible.funds_move(step.action_kind, control, step.args)]
    return hits, control


def decide(step, before, *, grant, approval, paused, now: str, plan_reversible: bool = True,
           config: dict | None = None) -> PolicyDecision:
    """Run R1 to R9 and return the strictest outcome with every hit."""
    step_digest = plan_mod.step_digest(step)
    hits = _r1(step)
    if target_key(step) in paused:
        hits.append(_hit("R2.paused", "stop", "this target is paused after a stop; a person clears it"))
    flags, control, tier = (), None, None
    if before is None:
        hits.append(_hit("R9.no-evidence", "refuse", "no before evidence was captured"))
    else:
        flags = injection.flag_spans(before.text)
        content_hits, control = _content_rules(step, before)
        hits += content_hits
    check = tiers.check(step.action_kind, _tier_target(step), grant)
    tier = check.to_dict()
    if not check.allowed:
        hits.append(_hit("R6.tier", "refuse", check.reason))
    hits += [_hit("R7.irreversible", "confirm", r) for r in irreversible.classify(
        step.action_kind, control, declared=step.declared_irreversible, plan_reversible=plan_reversible)]
    if before is not None:
        hits += _r8(step, before, flags) + _r9(step, before, control)
    else:
        hits += [_hit("R9.post-condition", "refuse", p) for p in [plan_mod.post_condition_problem(step)] if p]
    outcome = max((h["outcome"] for h in hits), key=RANK.__getitem__, default="pass")
    before_digest = before.digest if before is not None else None
    ref = _approval_ref(approval, step_digest, before_digest, now) if outcome == "confirm" else None
    if ref is not None:
        outcome = "pass"
    inputs = plan_mod.digest({"step": step_digest, "before": before_digest, "tier": tier,
                              "approval": ref, "paused": sorted(paused), "now": now,
                              "plan_reversible": plan_reversible})
    return PolicyDecision(outcome, hits, tier, ref, policy_digest(config), inputs,
                          pause=any(h["rule"] == "R3.challenge" for h in hits), injection_flags=flags)
