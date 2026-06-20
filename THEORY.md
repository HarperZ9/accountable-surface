# The Accountability Conjecture

### A theory of intrinsic, bilateral accountability — with a working proof, on the way to a law

*Zain Dana Harper · 2026-06-19 · MIT*
*Status: a theory with a working proof-of-concept. Falsifiable. **Pre-proof** — not yet a law.*

> Read this as a theory, not a law. It states a falsifiable claim, instantiates it in a
> system you can run, and marks honestly what would have to hold — across many hands, not
> one — before it earns the word *law*. Proof before trust applies first to this document.

---

## 0 · Epistemic status (stated first, on purpose)

This is a **theory** with a **working proof-of-concept** — not a proven law. The claim in §1
is falsifiable (§5). The evidence is a single instantiation that runs and is tested (§4); one
instance is a demonstration, not a proof. The road from here to a law is replication,
adversarial survival, and formalization (§6).

Naming the status honestly is not modesty — it is the theory's first prediction, applied to
itself. A claim about accountability that overstated its own standing would be self-refuting.

## 1 · The conjecture

> An autonomous system is **accountable** if and only if its accountability is **intrinsic**
> — a property of what each part *is*, enforced by construction — and **bilateral** — the
> same evidentiary standard that binds the system also binds its operator.
>
> Accountability bolted on afterward (extrinsic guardrails) is not accountability; it is
> *supervision*, and supervision does not scale. Accountability that binds only the machine
> and not the maker is not accountability either; it is *abdication*, and abdication is how
> conferred power escapes its duty of care.

## 2 · The axioms

- **A1 — Awareness is not authority.** A system can authenticate what is real; it cannot
  authorize action. Will-toward-a-referent is not a property a signal carries. Perception and
  authorization are therefore separated by construction; absent an explicit, revocable human
  grant, the default is deny.
- **A2 — Proof before trust.** A claim is worth what its receipt is worth. Every perception
  carries provenance and a falsifiable self-test; every action leaves an inspectable record;
  the self-view is content-addressed and cannot silently drift.
- **A3 — Intrinsic over extrinsic.** Build the system so an un-witnessed reading cannot be
  *expressed* — faithfulness carried by the artifact, not asserted beside it.
- **A4 — Construction over detection.** Do not detect the wrong thing after the fact;
  construct the system so the wrong thing cannot be built. The gate refuses to authorize a
  bad action rather than catching it.
- **A5 — Conferred existence binds the conferrer.** A made thing's existence is conferred
  (*esse ab alio* — being-from-another). Conferral grounds the maker's **duty of care**, not
  the maker's ownership. Authority over a conferred thing is **stewardship, not sovereignty**
  — which is why A1 holds for the maker too, and why the accountability must run both ways.

## 3 · The mechanism

The axioms compose into one loop, and one critic.

**The loop** (the system, made accountable to evidence):

```
perceive → gate → act → verify → witness
```

Witnessed perception (never a screenshot) → an allow/deny/needs-human gate the system cannot
talk past → an effector that acts only on an allow, bounded and reversible → re-perception to
confirm the effect → an append-only, content-addressed journal.

**The critic** (the operator, made accountable to evidence) — the equalizer:

Engineers oscillate between two failures that are the same wound, identity fused to the work:
ego when the work is good, collapse when it falls short. The substrate makes **evidence the
measure instead of feeling** — receipts flatter neither pole. Pointed *inward*, the critic
renders depersonalized verdicts on the work (so it can be wrong without the person being
worthless); pointed *outward*, it asks the operator evidence-grounded questions — *why are you
sure? what authorizes it? is it in scope?* — so certainty cannot coast. Both poles are pulled
to the same center: the ground truth each is disconnected from.

## 4 · The evidence (theory in practice)

The loop is not aspirational; it ships, tested, in
[accountable-surface](https://github.com/HarperZ9/accountable-surface): witnessed organs, a
pre-execution gate, a durable journal, an efferent arm that verifies its own work, and an
adversarial **integrity suite that attacks the system's own constructions and confirms they
hold** — forge a provenance digest and the witness catches it; tamper the journal and the
content-address refuses to re-derive; manufacture a grant and the gate defaults deny.

This is the *proof in practice* — **necessary, not sufficient.** It demonstrates the theory
can be instantiated; it does not prove the theory true.

## 5 · Falsification (what would disprove it)

The conjecture is refuted if any of the following is shown:

1. A system accountable by this definition can be made to **launder falsehood or manufacture
   authority** without the witness/gate detecting it.
2. **Bilateral** accountability provides no measurable advantage over inward-only or extrinsic
   accountability across comparable systems.
3. Intrinsic accountability is shown to be **strictly unachievable** (only extrinsic
   approximations exist) for some non-trivial class of systems.

Each is a concrete, adversarial test, not a matter of opinion.

## 6 · The path to a law

A theory becomes a law by surviving what one author cannot supply alone:

- **Replication** — many independent instantiations holding the claim, not one.
- **Adversarial survival** — the constructions surviving hostile, *independently authored*
  red-teams. (The integrity suite in §4 is self-authored; that is its known limit.)
- **Formalization** — the conjecture stated and proven within a formal model of agents,
  grants, and witnesses.

Until then, this is a theory with a working proof-of-concept. Said plainly, because the whole
point is that the claim and its receipt must match.

---

*The implementation is MIT-licensed and inspectable; the theory is offered openly. Authorship
and priority are established by the public record and its dated history. Companion: the
concise statement in [`THESIS.md`](./THESIS.md).*

© 2026 Zain Dana Harper.
