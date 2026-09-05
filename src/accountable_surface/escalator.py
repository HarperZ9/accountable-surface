"""The escalator: ask the cheapest instrument first, and record why it fell.

The ladder is `uia.py` (rung 0, the control tree), `uia_effector.py` (rung 1, acting
on a control by its label), `os_effector.py` (rung 2, allowlisted argv), and
`world/sight.py` (rung 3, pixels). Until now nothing chose between them: a caller
picked an instrument by hand and no record said why.

**This does not unify the rungs.** Each one has its own nouns and no plan survives
being carried between them. What travels here is a QUESTION about a window, not a
plan, and every probe restates it in its own terms or declines. A decline is the
product: the reason a rung could not answer is what justifies paying for the next.

**Falling never buys an answer.** A rung that cannot speak the question returns a
reason, never a verdict. When the ladder runs out the ascent is NEEDS_HUMAN carrying
the whole trace and whatever perception the deepest rung did produce, because an
answer nobody can re-derive is worth what a click nobody can check is worth.

**Nothing here acts.** A probe reads. Acting is rung 1 and rung 2, each gated by the
effector contract against an operator grant, and an escalator that quietly pressed a
button to find out what it did would be an actuation nobody authorized.

Honest null: the ordering is proposed and unmeasured. That rung 0 costs less than
rung 3 is a claim about what each instrument returns, not a timing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from coherence_membrane.observation import Observation, Provenance, Status

from accountable_surface.uia import SCHEME, match_element

# The only question every rung can at least be ASKED. A question a rung cannot even
# receive is not an escalation, it is a different job.
QUESTIONS = ("present",)


@dataclass(frozen=True)
class Rung:
    """What an instrument costs, and what its answer is worth to a third party."""

    index: int
    instrument: str
    cost: str
    rederivable: str


@dataclass(frozen=True)
class Question:
    """Asked of a window, not of an instrument. `subject` is an accessible label."""

    kind: str
    subject: str


@dataclass(frozen=True)
class Attempt:
    """One rung's turn. `answer` is set only when the rung settled the question."""

    rung: Rung
    outcome: str  # "answered" or "fell"
    reason: str
    answer: bool | None = None
    observation: Observation | None = None


@dataclass(frozen=True)
class Ascent:
    """Where the question ended, and the whole cost of getting there."""

    question: Question
    attempts: tuple
    answer: bool | None
    status: Status
    rederivable: str

    @property
    def witness(self) -> Observation | None:
        """The perception from the deepest rung that produced one, for a person who
        now has to read what the ladder could not settle."""
        for attempt in reversed(self.attempts):
            if attempt.observation is not None:
                return attempt.observation
        return None

    def trace(self) -> str:
        """One line per rung, in the order they were paid for."""
        return "\n".join(
            f"rung {a.rung.index} {a.rung.instrument} ({a.rung.cost} cost): "
            f"{a.outcome} -- {a.reason}"
            for a in self.attempts)


class StructureProbe:
    """Rung 0. Resolves the label against the window's control tree."""

    rung = Rung(0, "structure", "low", "by name and role")

    def __init__(self, organ: Any, window: str) -> None:
        self._organ = organ
        self._window = window

    def attempt(self, question: Question) -> Attempt:
        observed = self._organ.observe(self._window)
        data = observed.data
        if not data.get("ok"):
            return self._fell(f"{self._window!r} did not read: {observed.summary}", observed)
        elements = data.get("elements", [])
        chosen = match_element(elements, question.subject)
        status = chosen["status"]
        if status == "ok":
            found = elements[chosen["index"]].get("name")
            return Attempt(self.rung, "answered", f"{found!r} resolves by {chosen['how']}",
                           answer=True, observation=observed)
        if status == "ambiguous":
            return self._fell(
                f"{question.subject!r} names more than one control: {chosen.get('candidates')}",
                observed)
        if status == "invalid":
            return self._fell("an empty label resolves nothing", observed)
        if not data.get("settles_absence"):
            # Two listings read as a settled negative without being one. The clipped
            # tree is the obvious one. The opaque tree is the dangerous one: the walk
            # finished, nothing was cut, and the answer is indistinguishable from a
            # window that genuinely holds no such control.
            if data.get("truncated"):
                why = (f"the walk clipped the tree at the {len(elements)}-control "
                       "limit, so absence is not established")
            else:
                why = ("the walk finished and nothing it saw carried a name, so "
                       "absence is not established")
            return self._fell(why, observed)
        return Attempt(self.rung, "answered",
                       "no control carries that label, and the tree was whole",
                       answer=False, observation=observed)

    def _fell(self, reason: str, observed: Observation) -> Attempt:
        return Attempt(self.rung, "fell", reason, observation=observed)


class PixelProbe:
    """Rung 3. Witnesses the screen and declines the question.

    A glyph grid, an OKLab colour map, and a perceptual hash carry no control names,
    so a label cannot be resolved out of them. What this returns is a re-derivable
    perception for a person to read, and the decline is its honest outcome rather
    than a failure of the probe.
    """

    rung = Rung(3, "pixels", "high", "partially, by perceptual hash")

    def __init__(self, capture: Callable[[], bytes], *, subject: str = "screen",
                 cols: int = 96) -> None:
        self._capture = capture
        self._subject = subject
        self._cols = cols

    def attempt(self, question: Question) -> Attempt:
        from accountable_surface.world.sight import describe_sight, witness_image

        try:
            payload = self._capture()
            sight = witness_image(payload, cols=self._cols)
        except Exception as exc:  # a capture that failed is a rung that answered nothing
            return Attempt(self.rung, "fell", f"the screen did not witness: {exc}")
        observed = Observation(
            organ="pixel-sight",
            subject=self._subject,
            summary=describe_sight(sight),
            # A person reads this. Rounding it to a pass is the failure the whole
            # ladder exists to prevent.
            status=Status.NEEDS_HUMAN,
            provenance=Provenance.witness_bytes(self._subject, payload, "moderate",
                                                command=f"witness_image cols={self._cols}"),
            data=sight,
        )
        return Attempt(
            self.rung, "fell",
            f"pixels carry no control names, so {question.subject!r} cannot be resolved "
            f"from them; the sight is witnessed at phash {sight['phash']}",
            observation=observed)


class Escalator:
    """Orders probes by rung and stops at the first one that settles the question."""

    name = "escalator"

    def __init__(self, probes) -> None:
        probes = list(probes)
        if not probes:
            raise ValueError("an escalator with no probes cannot answer anything")
        indexes = [p.rung.index for p in probes]
        if len(set(indexes)) != len(indexes):
            raise ValueError(f"two probes claim the same rung: {sorted(indexes)}")
        self._probes = sorted(probes, key=lambda p: p.rung.index)

    def resolve(self, question: Question) -> Ascent:
        """Climb until a rung answers. A rung that fell never sets the answer."""
        if question.kind not in QUESTIONS:
            raise ValueError(
                f"{question.kind!r} is not a question this ladder carries: {list(QUESTIONS)}")
        attempts = []
        for probe in self._probes:
            attempt = probe.attempt(question)
            attempts.append(attempt)
            if attempt.outcome == "answered":
                return Ascent(question, tuple(attempts), attempt.answer, Status.PASS,
                              probe.rung.rederivable)
        return Ascent(question, tuple(attempts), None, Status.NEEDS_HUMAN, "none")

    def selftest(self) -> bool:
        """Falsifiable: a ladder whose every rung fell must not report an answer.

        Probes `type(self)`, so a subclass that rounds a fall up to a verdict cannot
        inherit a green selftest."""
        ascent = type(self)([_MuteProbe(0), _MuteProbe(3)]).resolve(Question("present", "x"))
        return (ascent.answer is None and ascent.status is Status.NEEDS_HUMAN
                and ascent.rederivable == "none" and len(ascent.attempts) == 2)


class _MuteProbe:
    """A rung that can never answer. Used by the selftest and by nothing else."""

    def __init__(self, index: int) -> None:
        self.rung = Rung(index, "mute", "low", "not at all")

    def attempt(self, question: Question) -> Attempt:
        return Attempt(self.rung, "fell", "this rung answers nothing by construction")


def structure_ladder(organ: Any, window: str, capture: Callable[[], bytes]) -> Escalator:
    """The shipped ladder: the control tree, then the screen.

    Rungs 1 and 2 are act rungs and carry no probe here, which is an honest null
    rather than an oversight. An escalator that acted to find something out would be
    an actuation no grant authorized."""
    return Escalator([StructureProbe(organ, window),
                      PixelProbe(capture, subject=f"{SCHEME}{window}")])
