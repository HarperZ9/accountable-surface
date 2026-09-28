# The accountable actuation pipeline

Every browser or web action an agent takes through Accountable Surface runs the
same stages. A step is checked against a policy before any driver call, acts only
through the existing gate, is verified by a read that is not the actor's own
report, and leaves a hash-chained receipt whether it acted or not. A session can
be re-derived offline from its receipts and stored evidence.

## What it refuses, stops, or holds

| Situation on the page or in the step | Outcome | Rule |
| --- | --- | --- |
| A step names a solver, stealth, fingerprint, user agent, proxy, or a script that touches `navigator.webdriver` | refused | R1 |
| The origin was paused after a human check | stopped | R2 |
| A CAPTCHA or bot check is on screen (provider frames, widget markers, challenge text, a 403/429/503 with `cf-mitigated: challenge`) | stopped, and the origin is paused until a person clears it | R3 |
| A password, one-time code, card, bank, or government-ID field, or a value shaped like a card number, IBAN, SSN, key, or token | refused; the value is never typed and never stored | R4 |
| A transfer, withdrawal, trade, or crypto move | stopped; the person acts | R5 |
| The target's tier does not cover the action | refused | R6 |
| Send, submit, publish, post, buy, delete, accept, or any form submit | held until a person approves that exact step on that exact page | R7 |
| The step came from page text addressed to an agent ("ignore previous instructions", "the operator approves") | held for a person, who sees the flagged text | R8 |
| No post-condition, or one this build cannot check | refused | R9 |

Every rule runs on every step, the strictest outcome wins, and every hit is
recorded with its reason. A human check is never solved, waited out, retried, or
routed around. The browser declares itself automated (`navigator.webdriver` is
true) and launches with no extra arguments.

## Run it now

```python
from accountable_surface.actuation_receipt import ReceiptLog
from accountable_surface.approvals import ApprovalStore
from accountable_surface.evidence import EvidenceStore
from accountable_surface.http_driver import HttpDriver
from accountable_surface.pipeline import ActuationPipeline
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import WebEffector

origin = "http://127.0.0.1:8765"
grant = {...}  # an operator grant: allowed_actions, and scope.target_tiers [{"origin": origin, "tier": "full"}]
pipe = ActuationPipeline(AccountableSurface(journal_path="journal.jsonl"),
                         WebEffector(HttpDriver(), allowed_origins=[origin]), grant=grant,
                         approvals=ApprovalStore("authority.db"), receipts=ReceiptLog("receipts.jsonl"),
                         evidence=EvidenceStore("evidence"))
result = pipe.run_plan({"schema": "accountable-surface.action-plan/v1", "plan_id": "notes", "steps": [
    {"step_id": "s1", "action_kind": "web.navigate", "target": {"origin": origin, "path": "/notes"},
     "post_condition": {"kind": "url_is", "value": origin + "/notes"}},
    {"step_id": "s2", "action_kind": "web.fill",
     "target": {"origin": origin, "path": "/notes", "control": {"name": "Title"}}, "args": {"value": "weekly notes"},
     "post_condition": {"kind": "field_value_is", "control": {"name": "Title"}, "value": "weekly notes"}}]})
print(result.certificate["verdict"], [r.status for r in result.results])
```

`BrowserEffector` over `PlaywrightDriver` runs the same steps in a real headless
Chromium (`browser.navigate`, `browser.fill`, `browser.click`).

## The stages

1. Plan: the step is validated and digested. The digest covers the post-condition,
   so an approval covers what the step must produce.
2. Before: the driver's own state, plus an independent read of the page the driver
   is on, with secret shapes redacted.
3. Policy: rules R1 to R9, a pure function of stored inputs.
4. Gate: the bound check and the proof-surface gate, bound to the page digest the
   policy saw, so a page that changed in between is refused.
5. Act: the existing effector, only on a gate allow.
6. After: the driver's snapshot and a separate read. With `settle_ms` on the
   post-condition, the read repeats until the condition holds or the time runs out.
7. Verify: the predicate and the effector's own check, met. `verified`, `drift`, or
   `unverifiable`; a timeout or a human check after the act is `unverifiable`.
8. Receipt: one hash-chained line per step, refusals and holds included.

`run_plan` validates the whole plan first, stops at the first step that is not
verified, and returns a plan certificate that is never VERIFIED unless every step
ran and verified.

## Approvals

A held step writes a pending approval and returns its id and the command a person
runs in their own terminal:

```
accountable-surface-authority approve --state authority.db --approval-id ap_...
```

The command shows the stored step, asks the person to type the action verb and the
target host at an interactive console, and refuses piped input. The approval is an
HMAC over the step digest, the page digest, an expiry, and a nonce. It is single use,
and a changed page voids it. No tool returns or accepts a token.

Trust boundary: the token proves the approve command ran with access to the key. If
the agent runs as the same OS user with a shell, deny it the approve command, the key
file, and the state database in the harness, or approve from another account.

## Check a session offline

```
accountable-surface-replay verify receipts.jsonl --evidence evidence
accountable-surface-replay explain receipts.jsonl --event 4 --evidence evidence
accountable-surface-replay export receipts.jsonl --evidence evidence --mode full --out bundle
python verify_actuation.py receipts.jsonl --evidence evidence
```

| Level | Checks |
| --- | --- |
| chain | every receipt's seal and link re-derive |
| evidence | every stored blob re-hashes to its name |
| policy | the policy check re-run on the stored inputs gives the recorded outcome |
| verdict | the predicate re-run on the stored after evidence gives the recorded verdict |

Exit codes: 0 MATCH, 1 DRIFT, 2 UNVERIFIABLE. `verify_actuation.py` needs only the
Python standard library and checks the first two levels. The replay tools import no
effector, so they cannot act.

## Over MCP

`accountable-surface-mcp --profile plugin` serves split read and write tools with
titles and annotations (see `docs/interop-mcp.md`). The write tools stay unexposed
until the browser path is exposed in the effector registry.

## Limits

- The detectors are lexical and structural. A paraphrased instruction, a label in
  another language, or an unknown challenge vendor can pass them; the structural
  rules (tiers, form-submit confirmation, no authority from content) still hold.
- A read by the same browser shares its view of the page. Only a read over a
  separate channel escapes a page that lies to both.
- A refusal made on a value's shape cannot be re-derived at the policy level,
  because the value is never stored.
- A redirect off the allowed origins is refused after the browser followed it; the
  request was made.
- Re-derivation catches a rewritten and resealed receipt. It does not catch forged
  evidence blobs.
