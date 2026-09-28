"""One catalog of MCP tools: names, titles, descriptions, schemas, annotations.

The three servers read their tool lists from here, so a title or a hint cannot
drift between them:

    interop   interop_mcp.py, profile "interop": the manifests' eight tools, with
              the legacy dotted names and the mixed `actuate`
    plugin    interop_mcp.py, profile "plugin": read and write split, one write
              tool per action class, plain names (the client namespaces them)
    fastmcp   server.py, the FastMCP server
    health    mcp.py, the bundled-lane health shim

The operator picks the profile with a server argument; no tool argument does.
Annotations follow the MCP ToolAnnotations fields. The SDK calls every one a
hint a client must not trust, so they are the second prompt, never the
boundary: the policy check and the gate stay the boundary. "Read-only" means a
tool changes nothing outside the surface's own append-only audit record.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["CATALOG", "READ_KINDS", "WRITE_KINDS", "ToolSpec", "definitions", "names", "names_by_mode",
           "replace", "spec"]

PREFIX = "accountable-surface."
READ_KINDS = frozenset({"native.device.ls", "perceive", "propose"})
WRITE_KINDS = frozenset({"web.navigate", "web.fill", "web.submit", "browser.navigate", "browser.fill",
                         "browser.click", "approval.withdraw"})

_STR = {"type": "string"}
_CONTROL = {"type": "object", "properties": {"name": _STR, "role": _STR, "ref": _STR}, "additionalProperties": False}
_POST = {"type": "object", "properties": {"kind": _STR, "value": _STR, "path": _STR, "control": _CONTROL,
                                          "forbid": {"type": "array", "items": {"type": "object"}}}}
_PAGE = {"origin": _STR, "path": _STR}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    properties: dict
    required: tuple = ()
    mode: str = "read"  # read | write | mixed
    kinds: tuple = ()
    open_world: bool = False
    idempotent: bool | None = None
    destructive: bool | None = None

    @property
    def read_only(self) -> bool:
        return self.mode == "read"

    def annotations(self) -> dict:
        destructive = (not self.read_only) if self.destructive is None else self.destructive
        idempotent = self.read_only if self.idempotent is None else self.idempotent
        return {"title": self.title, "readOnlyHint": self.read_only, "destructiveHint": destructive,
                "idempotentHint": idempotent, "openWorldHint": self.open_world}

    def schema(self, strict: bool = False) -> dict:
        out: dict = {"type": "object", "properties": dict(self.properties)}
        if self.required:
            out["required"] = list(self.required)
        if strict:
            out["additionalProperties"] = False
        return out


def _t(name, title, description, properties=None, required=(), **kw) -> ToolSpec:
    return ToolSpec(name, title, description, properties or {}, tuple(required), **kw)


_LOOP = ("through the accountable pipeline: the policy check, the gate, the act, an independent readback, "
         "a typed verdict, and a hash-chained receipt. A CAPTCHA or bot check on the page stops the step and "
         "pauses the origin until a person handles it.")

CATALOG: dict[str, ToolSpec] = {s.name: s for s in (
    _t("status", "Server status", "Network-free identity: name, version, tools, and primitives. A fast liveness "
       "probe; no perception, no gate, no action."),
    _t("doctor", "Readiness report", "Readiness: identity, the tools this server lists, and its dependency "
       "checks; where the action runtime loads, also the grants, the exposed effectors or wired verbs, and the "
       "receipt store. Reads only."),
    _t("perceive", "Perceive a target", "Witness a subject as an Observation with its provenance digest: a "
       "directory (an independent os.scandir witness), a web page, or a file. Reads only.",
       {"subject": _STR}, ["subject"], kinds=("perceive",), open_world=True),
    _t("propose", "Check one action against the gate", "Check an action (action_kind, target) against the "
       "operator's grants at the pre-execution gate and return allow, deny, or needs-human. Advisory: it never "
       "acts, and with no grant the answer is deny.",
       {"action_kind": _STR, "target": _STR, "expected_digest": _STR}, ["action_kind", "target"],
       kinds=("propose",), open_world=True),
    _t("actuate", "Actuate one action (legacy)", "Run the full loop for a wired safe verb: read the target, plan, "
       "check the gate, act, read back, verify independently, record, and emit an action-receipt/v1. Only "
       "native.device.ls is wired; every other kind is refused. A failed reversible act is rolled back.",
       {"action_kind": _STR, "target": _STR, "content": {"type": "array", "items": _STR},
        "expected_digest": _STR, "idempotency_key": _STR}, ["action_kind", "target"],
       mode="mixed", kinds=("native.device.ls",), open_world=True),
    _t("device_ls", "List a directory", "List a directory through the accountable loop (native.device.ls), "
       "checked against the surface's own independent witness. Takes a path. Reads only.",
       {"path": _STR}, ["path"], kinds=("native.device.ls",)),
    _t("journal", "Read the session journal", "Return this session's journal (perceptions, gate decisions, "
       "actuations) with a re-derived chain-integrity verdict. Reads only."),
    _t("receipt", "Verify the action receipts", "Re-derive the action-receipt/v1 store offline: MATCH, DRIFT, "
       "or UNVERIFIABLE, with the store path. include_events also returns the redacted events. Reads only.",
       {"include_events": {"type": "boolean"}}),
    _t("session_journal", "Read the journal", "Return every perception and decision in the journal, including "
       "entries replayed from earlier sessions when journal persistence is on. Reads only."),
    _t("interocept", "Read the surface's own session", "A witnessed, tamper-evident view of what the surface "
       "has perceived and what the gate decided (counts and a journal digest). Grants no authority, changes "
       "nothing."),
    _t("check_plan", "Check a plan against policy", "Check one step or a whole action plan against the policy "
       "(secret fields, human checks, irreversible actions, tiers, post-conditions) without acting. Reads the "
       "page a step names; writes no pending approval and no receipt.",
       {"plan": {"type": "object"}}, ["plan"], kinds=("propose",), open_world=True),
    _t("receipt_verify", "Verify the receipt chain", "Re-derive the actuation receipts and their stored "
       "evidence at the chain, evidence, policy, and verdict levels, each MATCH, DRIFT, or UNVERIFIABLE. "
       "Reads only.", {"level": {"type": "string", "enum": ["chain", "evidence", "policy", "verdict"]}}),
    _t("approvals_pending", "List pending approvals", "List the approvals waiting for a person: each step's "
       "rendering and the terminal command the person runs to approve it. Returns no token."),
    _t("browser_navigate", "Navigate the browser", "Go to a page on a granted origin " + _LOOP + " Returns the "
       "verdict, the policy outcome with every rule and reason, and the receipt reference.",
       {**_PAGE, "post_condition": _POST}, ["origin", "path"], mode="write", kinds=("web.navigate", "browser.navigate"),
       open_world=True, idempotent=False),
    _t("browser_fill", "Fill a form field", "Fill one form field, named by its accessible name, " + _LOOP +
       " A secret field or a secret-shaped value is refused and never typed; the person types it.",
       {**_PAGE, "control": _CONTROL, "value": _STR, "post_condition": _POST}, ["origin", "path", "control", "value"],
       mode="write", kinds=("web.fill", "browser.fill"), open_world=True, idempotent=False),
    _t("browser_click", "Click a control", "Click one control, named by its accessible name, " + _LOOP +
       " A click that sends, submits, buys, deletes, or accepts is held until a person approves that exact step.",
       {**_PAGE, "control": _CONTROL, "post_condition": _POST}, ["origin", "path", "control", "post_condition"],
       mode="write", kinds=("browser.click",), open_world=True, idempotent=False),
    _t("browser_submit", "Submit a form", "Submit a form " + _LOOP + " A submit is always held until a person "
       "approves that exact step on that exact page.",
       {**_PAGE, "control": _CONTROL, "action": _STR, "expect_title": _STR, "post_condition": _POST},
       ["origin", "path", "control", "post_condition"], mode="write", kinds=("web.submit",), open_world=True,
       idempotent=False),
    _t("run_plan", "Run an action plan", "Run an accountable-surface.action-plan/v1 plan step by step " + _LOOP +
       " Stops at the first step that is not verified and returns every step's verdict and the plan certificate.",
       {"plan": {"type": "object"}}, ["plan"], mode="write",
       kinds=("web.navigate", "web.fill", "web.submit", "browser.navigate", "browser.fill", "browser.click"),
       open_world=True, idempotent=False),
    _t("withdraw_approval", "Withdraw a pending approval", "Withdraw a pending approval request, so a person is "
       "no longer asked about it. It cannot approve anything.",
       {"approval_id": _STR}, ["approval_id"], mode="write", kinds=("approval.withdraw",), idempotent=True,
       destructive=False),
)}

SERVERS: dict[str, tuple[str, ...]] = {
    "interop": ("perceive", "propose", "actuate", "device_ls", "journal", "receipt", "status", "doctor"),
    "plugin": ("status", "doctor", "perceive", "check_plan", "journal", "receipt_verify", "approvals_pending",
               "device_ls", "browser_navigate", "browser_fill", "browser_click", "browser_submit", "run_plan",
               "withdraw_approval"),
    "fastmcp": ("perceive", "propose", "actuate", "session_journal", "interocept", "status", "doctor"),
    "health": ("status", "doctor"),
}
PREFIXED = frozenset({"interop", "health"})


def spec(name: str) -> ToolSpec:
    short = name[len(PREFIX):] if name.startswith(PREFIX) else name
    return CATALOG[short]


def names(server: str) -> list[str]:
    prefix = PREFIX if server in PREFIXED else ""
    return [prefix + n for n in SERVERS[server]]


def names_by_mode(server: str, mode: str) -> list[str]:
    return [n for n in names(server) if spec(n).mode == mode]


def definitions(server: str) -> list[dict]:
    """The tools/list entries for a stdio server: name, title, description, input
    schema, and annotations. The plugin profile's schemas are closed, so an
    argument outside them is refused before anything runs."""
    strict = server == "plugin"
    return [{"name": n, "title": spec(n).title, "description": spec(n).description,
             "inputSchema": spec(n).schema(strict=strict), "annotations": spec(n).annotations()}
            for n in names(server)]
