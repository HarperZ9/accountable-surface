# Senses and Sensibility -- a thesis on accountable machines

*Zain Dana Harper · 2026-06-19 · MIT*

> Senses and sensibility are what lead to the new frontier. Machines learning to hold
> themselves accountable.

## The claim

An agent that perceives the world through unverified channels and is governed by guardrails
bolted on after the fact is not accountable -- it is merely supervised, and supervision does
not scale. The alternative is to make accountability **intrinsic**: a property of what each
part *is*, enforced by construction, not added as a layer. This is a thesis about building
that, and a working artifact ([accountable-surface](https://github.com/HarperZ9/accountable-surface))
that demonstrates it.

## Four principles

**1. Awareness is not authority.** A system can authenticate what is real; it cannot
authorize action. Knowing that something is the case is not the same as having the right to
act on it -- and will-toward-a-referent is not a property a signal carries. So perception and
authorization are separated by construction: the model perceives freely and authorizes
nothing; only an explicit, revocable human grant gates an action; absent a grant, the default
is deny.

**2. Proof before trust.** A claim is worth what its receipt is worth. Every perception
carries provenance and a falsifiable self-test; every action leaves an inspectable record;
the self-view is content-addressed and cannot silently drift. Trust is not asked for -- it is
earned, per claim, against evidence.

**3. Intrinsic over extrinsic.** A screenshot laid beside a page proves nothing about the
page; nothing about the artifact entails that it is faithful. A perception *organ* makes
faithfulness intrinsic -- the reading carries its own provenance and a self-test that can
fail. Build the system so an un-witnessed reading cannot even be expressed.

**4. Construction over detection.** Do not detect whether the output is right after the fact;
construct the system so the wrong thing cannot be built. The gate does not catch a bad
action -- it refuses to authorize one.

## The accountable loop

These principles compose into one loop, and it is real, not aspirational -- it ships, tested:

```
perceive → gate → act → verify → witness
```

- **Perceive** -- witnessed observations from inert organs (provenance + a falsifiable
  self-test), never a screenshot.
- **Gate** -- every proposed action is checked against the operator's grant: allow / deny /
  needs-human. The model cannot supply its own authorization.
- **Act** -- an effector acts *only* on an allow, bounded by construction, reversibly; the
  motor arm may mutate the world but can never *grant* authority.
- **Verify** -- the surface re-perceives to confirm the effect; nothing is assumed-done; a
  failed reversible act rolls back.
- **Witness** -- every perception and decision is journaled, append-only, content-addressed,
  durable across sessions.

## The equalizer -- accountability turned both ways

The deeper claim is that this is not only a machine architecture. It is a discipline the
*builder* needs as much as the machine.

Engineers oscillate between two failures that are the same wound: identity fused to the work.
When the work is good, the fusion reads as ego; when it falls short, the same fusion reads as
collapse. God one minute, nothing the next -- same circuit, different input. Neither pole is
correctable by feeling, because feeling is the broken instrument.

An accountability substrate is the equalizer, because it makes **evidence the measure instead
of feeling.** Receipts are indifferent in both directions -- they do not flatter the god, they
do not wound the collapse; they report what the artifact does. The same line governs both:
*the gate judges the action, never the worth of whoever took it.* Held to account is not a
verdict on the self.

So the critic is bilateral. Pointed **inward**, it renders verdicts on the work -- a failed
test, a drift, a broken invariant -- depersonalized, so the work can be wrong without the
person being worthless. Pointed **outward**, it asks the operator evidence-grounded
questions -- *why are you sure? what authorizes it? is it in scope?* -- so certainty cannot
coast unexamined. Both poles are pulled to center by the same thing: the ground truth each is
disconnected from. The self-critic ignores the green; the grandiose ignores the red; the
substrate makes both look at the actual state.

## What this is not

It is not a guardrail, not a policy layer, not a wrapper. It does not defeat anyone's safety
mechanisms; it does the opposite -- it makes a machine's own perception and action witnessed
and gated, and it makes the builder's own work answerable to evidence. The strongest version
is honest about its own limits, in public, with receipts -- including this one.

## Addendum -- 2026-06-21

*Additive note, appended after publication. It supplements the thesis above; it does not
revise any claim in it.*

**The problem the accountable loop pays down -- Naur's theory-building.** Peter Naur,
*Programming as Theory Building* (1985), argues that the code is not the program: the program
is the *theory* in the programmer's head -- how and why the parts connect. A generated artifact
is the *shadow* of that theory; the theory is what is lost when an agent produces code on
demand. This names precisely what an accountability substrate is *for*. The tax of trusting an
artifact whose theory you do not hold is **comprehension debt**, and a re-checkable receipt is
a debt-payment mechanism: checking is cheaper than re-deriving, so trust no longer requires
re-holding the whole theory. The loop here witnesses the *form* -- the criterion, the proof --
not merely the output. **Honest bound:** this *supplements* human theory-building; it does not
*replace* the skill Naur prescribes. It catches what un-built judgment misses and carries the
theory as a witness -- a tool answer to what is partly a skill problem.

**The premise turned on itself -- criterion independence.** This thesis rests on judging an
artifact against a criterion it did not author ("proof before trust"). Turning that standard
on the substrate itself surfaced a seam: a self-graded check (the criterion's author is also
the artifact's producer) was, by the system's own records, indistinguishable from an
independent one. The closure: record `author`/`producer` provenance, and downgrade a
self-authored verdict to **UNVERIFIABLE** ("independence not witnessed") rather than letting it
pass as decided. **Honest bounds, verbatim:** this is an **empirical demonstration plus a
mechanism, not a proven theorem** -- it shows the premise was unwitnessed and is now
witnessable/enforceable; it does not prove independence is always decidable. The witness is
**provenance-recorded, not cryptographic** -- `author`/`producer` are claimed ids; this is
trust-minimization, not trust-elimination (a forged id is the residual trust). And the
enforcement is **opt-in** (strict mode off by default); the seam is closed where it is enabled,
and elsewhere the system emits the honest independence annotation alongside the verdict.

---

*The implementation is MIT-licensed and inspectable; the thesis is offered openly. Authorship
and priority are established by the public record and its dated history.*

© 2026 Zain Dana Harper.
