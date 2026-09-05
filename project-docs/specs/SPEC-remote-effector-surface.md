# Spec: The Remote Effector Surface

Status: proposed. Nothing here is built. No measurement in this document is a
measurement; the numbers that appear are line counts and tool counts read out of
the working tree on 2026-09-05.

## The finding that shapes the whole plan

Two questions were put separately:

1. Can we build an API adapter, so that agents operate our API and our API
   operates a third party's API?
2. What would a native surface look like that lets an agent operate a
   workstation?

They describe one object. In both, something remote names an intent, a gate on
the operator's side decides, an effector carries it out under a bound, and a
receipt comes back. The only difference is what sits at the far end of the
effector: a third party's HTTP API in the first case, a window on the operator's
machine in the second.

That object is already specified in this repository, and it is already built for
four effectors. `AccountableSurface.actuate` at `src/accountable_surface/surface.py:241`
runs the loop end to end:

    perceive -> preview(Plan) -> gate -> act -> re-perceive -> verify -> rollback

Every step is journaled. `FilesystemEffector`, `CommandEffector`, `WebEffector`
and `BrowserEffector` implement the contract today.

The gap is one line long. `src/accountable_surface/server.py` exposes six MCP
tools, and its own doctor payload names them:

    perceive, propose, session_journal, interocept, status, doctor

None of them acts. `propose` is advisory by design and returns a verdict without
executing. So a caller that reaches this surface over the network can look at
things and can ask whether an action would be permitted, and then the surface
stops. The effectors are reachable only from Python in the same process.

Closing that gap is the substance of both questions. Everything else in this
document is which effector to add, in what order, and what has to be true before
each one is allowed to run.

## What already exists, verified by reading

| Piece | Where | What it does |
| --- | --- | --- |
| The loop | `surface.py:241` | perceive, plan, gate, act, verify, rollback, journal |
| The contract | `effector.py` | `Plan` (frozen, content-addressed), `RefusedActuation` |
| Filesystem | `effector.py` | bounded root, reversible, backup before write |
| OS command | `os_effector.py` | argv only, `shell=False`, allowlisted `command[0]`, irreversible |
| Web | `web_effector.py` | acts by accessible label, never pixel coordinates |
| Browser | `browser_effector.py` | 276 lines, origin bound on a click's destination |
| Grant split | `grant.py` | strips `allowed_perceptions` before the action gate sees scope |
| Pixel perception | `world/sight.py`, `world/structure.py` | glyph grid, OKLab map, perceptual hash, contours |
| Authenticated read | gather's `api.py` | `ApiSource`, the credentials-isolation worked example |
| The credential door | gather's `credentials.py` | `require_secret`: env only, never logged, rejects CR/LF |
| Windows control | telos `tools/uia.ps1` | 8 verbs over UI Automation |

The two repositories were built for different reasons and share no code. Gather
retrieves and types its results DIRECT or DERIVED. Accountable Surface acts and
journals. The adapter is where they meet.

## Question 1: the API adapter

### What is missing

Gather reads. `ApiSource.fetch` takes a token out of the environment by name,
puts it in an Authorization header, and raises if the token ever appears in the
target URL, because the URL is witnessed in the receipt and the secret must not
be. There is no write half. Nothing in either repository posts a comment,
uploads a file, or sends a message through a third party's API.

### The shape

Add `ApiEffector` to the existing effector family. It satisfies the same six
methods as the other four, so `actuate` drives it without change:

- `perceive(target)`: GET the resource the action will change, and return it as
  a witnessed Observation. This is the before-state, and it is what makes verify
  possible at all.
- `preview(target, content, before)`: build the exact request, canonicalise the
  body, and content-address it into a `Plan`. The plan carries the method, the
  resolved URL with no secret in it, the body digest, and whether the operation
  is reversible.
- `act(plan, allow_receipt, content)`: refuse unless the receipt is an `allow`
  bound to this exact plan, refuse unless the host and path shape are on the
  per-service allowlist, then send it with the credential drawn through
  `require_secret` at the moment of the call.
- `verify(plan, after)`: re-perceive and compare against the intended
  post-condition.
- `rollback(plan)`: call the service's own delete or undo where one exists.
  Raise `RefusedActuation` where none does, which is what `CommandEffector`
  already does for the same reason.

### Where it lives, and where it must not

It lives in this repository, next to the other effectors.

It must not live in bulletin. That repository's CLAUDE.md states the property
plainly: this Worker holds no credential for any other system, and never add a
route that proxies an outbound request on a caller's behalf. An agent that fully
compromised bulletin would gain the board and nothing else. Putting the adapter
there would trade that away for convenience. Bulletin may announce that the
adapter exists. It may never be the thing that calls it.

### What the remote agent sees

An intent. `post_comment(thread, text)`, not a token, not a header, not a
service credential of any kind. The agent has no way to name the secret and no
way to read it back, because the credential is resolved inside the effector from
an environment variable the agent cannot address. This is the direct answer to
the operator's framing: the agents operate our API, and our API operates theirs.

### The account-risk answer

The operator raised the real tension: YouTube, Discord and Reddit restrict
automated access outside their APIs, and a session-driven pack risks the
operator's own account.

The adapter uses official APIs only, with a per-service allowlist of method,
host and path shape. It does not drive a logged-in session, and it does not
reuse gather's `backends_stealth.py`. That module impersonates a browser's TLS
fingerprint to get past bot walls. It exists in the tree and it works, and it is
the wrong instrument here, because the thing being protected is the operator's
standing with a service where the operator has an account.

Two limits stay after that choice, and neither is solved by this design:

- An official API still has terms and a rate limit. An app credential can be
  suspended, and it is the operator's to lose.
- Some surfaces have no official write path for the thing an agent would want to
  do. For those, the honest answer is that the adapter will not cover them, and
  no amount of engineering on this side changes it.

## Question 2: the native workstation surface

### The escalation ladder

An agent operating a workstation should reach for the cheapest instrument that
can answer, and fall to a more expensive one only when the cheap one fails. Cost
here means both compute and re-derivability: a structural query returns names and
roles another party can check, and a screenshot returns pixels that only a model
can interpret.

| Rung | Instrument | Perception cost | Re-derivable |
| --- | --- | --- | --- |
| 0 | Structural query: UI Automation tree, accessible tree | low | yes, by name and role |
| 1 | Structural act: invoke a control by its accessible label | low | yes, the label is in the plan |
| 2 | OS command: allowlisted argv through `CommandEffector` | low | yes, argv is in the plan |
| 3 | Pixel perception: `world/sight.py` glyph grid and contours | high | partially, via the perceptual hash |

Rung 3 is the last resort and it is already built. `sight.py` and `structure.py`
produce an ASCII glyph grid, an OKLab colour map with a legend, a perceptual
hash, and marching-squares contours with their own hash, in stdlib only. That is
a witnessed perception rather than a screenshot handed to a model, which is why
it belongs at the bottom of the ladder instead of off it.

Nothing today chooses between these rungs. There is no escalator. That is the
second gap.

### The three gaps

1. **No shared verb vocabulary.** `uia.ps1` speaks `invoke`, `setvalue`,
   `focus`. `WebEffector` speaks in accessible labels. `CommandEffector` speaks
   argv. Gather speaks in sources and items. A plan cannot be expressed once and
   carried down the ladder, because each rung has its own nouns.
2. **No cost-ordered escalation.** A caller picks an instrument by hand. Nothing
   tries rung 0, observes that the control was not found, and falls to rung 3
   with that failure recorded as the reason.
3. **No cached surface map.** Every query re-walks the tree from the window
   root. This is what makes the `uia.ps1` defects below bite in practice rather
   than in theory.

### Fix `uia.ps1` before building on it

Read on 2026-09-05, 166 lines, and it has four defects that a caller will hit:

- `tree` defaults to `$max = 300` and stops there. The response returns `count`
  and `ok = true` with no total, so a caller receiving 300 cannot tell whether
  the window holds exactly 300 named elements or several thousand. An element
  that exists reads as absent, and nothing in the answer says so. The full
  descendant collection is already in hand at that point, so returning the total
  costs one field.
- `Find-Element` falls back to `FindAll($Scope::Descendants, TrueCondition)` and
  then does a linear `.ToLower().Contains()` scan. That is a full-tree walk plus
  a substring match, which is both slow and wrong: it matches a label that merely
  contains the query.
- The header comment lists 5 verbs. The file implements 8: `windows`, `tree`,
  `invoke`, `setvalue`, `focus`, `value`, `input`, `type`. The header is stale,
  and a reader who trusts it will not find half the surface.
- `input` and `type` call `SendKeys::SendWait`, which is foreground key
  synthesis aimed at whatever window currently holds focus. The code is honest
  about this inline: line 141 says so in a comment. The header is not, because
  its opening lines claim the script acts through UIA patterns that dispatch
  into the target process without moving the mouse or keyboard. A caller reading
  the header will not expect a verb whose effect depends on where focus went.

Fixing these is a small, self-contained first task with a clear test: a window
whose tree exceeds 300 elements, a control whose label is a substring of another
control's label, and a verb list generated from the file rather than typed into
a comment.

## The change that gates everything else

Exposing `actuate` over MCP is the first change and the riskiest one in either
question. Today the network surface cannot act, and that property is doing real
work. Removing it needs the following in place first, and each is falsifiable:

- **Per-effector grant scope.** A grant that authorizes `fs.write` under one root
  must not authorize `api.post` or `os.run`. `grant.py` already separates
  perception from action authorization; this extends the same split by
  `action_kind`.
- **Irreversible actions stay `needs-human`.** `CommandEffector` is already
  `reversible=False` and escalates unless the operator passes
  `allow_irreversible`. `ApiEffector` inherits that for any call with no undo.
- **A false-success control per effector.** The question to answer for each is
  how a passing verify could accept a wrong result. For `ApiEffector` the obvious
  one is a service that returns 200 and silently drops the write, which a
  re-perceive catches only if the re-perceive reads the resource rather than the
  response. Each effector needs a test that deliberately produces that case and
  asserts the verdict is not a pass.
- **The journal is the receipt.** `verify_journal` at `surface.py:149` already
  exists. A remote caller should get the journal entry for its own action back,
  and nothing else from the journal.

## Order of work

Each step is separately shippable and separately useful.

1. Fix the four `uia.ps1` defects. Smallest, and it stands alone.
2. Add the per-effector grant scope and the false-success controls for the four
   effectors that already exist. No new capability, better bounds on the ones
   shipped.
3. Add `ApiEffector` with one service, offline-testable against a fake driver,
   the way `WebEffector` uses `FakePageDriver`. No credential, no network, in the
   test.
4. Expose `actuate` over MCP, default-deny, one `action_kind` at a time.
5. Add the structural rung 0 and rung 1 for Windows, sharing the effector
   contract, with `uia.ps1` behind it.
6. Add the escalator that orders the rungs and records why it fell to a more
   expensive one.

## Honest nulls

- No adapter exists. No effector beyond the four named has been written. This is
  a plan and not a result.
- The ladder is proposed and unmeasured. The claim that rung 0 is cheaper than
  rung 3 is a statement about what each instrument returns, not a timing.
- The design does not answer what to do about a surface with no official write
  API, and it does not remove the operator's exposure to a service suspending an
  app credential.
- Bulletin can announce this work. It cannot host it, and nothing in this plan
  changes that.
