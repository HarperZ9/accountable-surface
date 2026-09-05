"""API actuation for the efferent arm -- write through a third party's OFFICIAL API,
under the same Effector contract as the other four.

The answer to "the agents operate our API, and our API operates theirs". What a
remote agent hands in is an intent: `post_comment` and a body. It cannot name a
credential, cannot set a header, cannot choose a host, and cannot read a token
back, because the secret is resolved inside `act` from an environment variable the
agent has no way to address.

Three bounds, each enforced at the moment of the call rather than trusted from the
plan:

  * the service allowlist -- method, host, and path SHAPE. An intent the service
    does not declare is refused; a target path the intent's shape does not match is
    refused, so `post_comment` cannot reach an admin route.
  * the gate allow -- the receipt has to be bound to this exact plan.
  * the credential -- drawn through `require_secret` at call time and sent in a
    header. The token is checked against the URL first, because the URL is what the
    surface witnesses into the journal and a secret must never land there.

Verification reads the RESOURCE, never the response. A service that answers 201 and
drops the write is the obvious way a passing verify could accept a wrong result, and
re-reading the collection is the only thing that catches it. `tests/test_false_success.py`
holds that case.

`FakeApiDriver` makes the whole contract testable offline with no network and no real
credential. The stdlib transport lives in `api_transport.py`, deliberately apart.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex

from accountable_surface.credentials import require_secret
from accountable_surface.effector import Plan, RefusedActuation, Verdict


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class ApiOperation:
    """One thing a remote agent may ask for, named by intent rather than by route."""

    intent: str  # what the agent names: "post_comment"
    action_kind: str  # what the gate authorizes: "api.post"
    method: str
    path_shape: str  # anchored regex the target path must match; named groups feed the undo
    undo_method: str = ""  # empty when the service offers no undo -> the plan is irreversible
    undo_shape: str = ""  # e.g. "/repos/{owner}/{repo}/issues/comments/{id}"

    @property
    def reversible(self) -> bool:
        return bool(self.undo_method)


@dataclass(frozen=True)
class ApiService:
    """A single third-party API, and the complete set of writes allowed against it."""

    name: str
    host: str
    auth_env: str
    operations: tuple[ApiOperation, ...]
    auth_scheme: str = "Bearer"
    scheme: str = "https"

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}"


@dataclass(frozen=True)
class ApiCall:
    """What the agent hands in. No token, no header, no host, no method."""

    intent: str
    body: dict = field(default_factory=dict)


GITHUB_ISSUE_COMMENTS = ApiService(
    name="github",
    host="api.github.com",
    auth_env="ACCOUNTABLE_SURFACE_GITHUB_TOKEN",
    operations=(
        ApiOperation(
            intent="post_comment",
            action_kind="api.post",
            method="POST",
            path_shape=r"/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)/comments",
            undo_method="DELETE",
            undo_shape="/repos/{owner}/{repo}/issues/comments/{id}",
        ),
    ),
)


class FakeApiDriver:
    """Deterministic in-memory API for tests and offline demos.

    Holds collections keyed by path. A POST appends a member and assigns an id; a
    DELETE removes one by id. Records every request it was handed, so a test can
    assert what did and did not travel (a credential, above all).
    """

    def __init__(self, collections: dict[str, list[dict]] | None = None) -> None:
        self._collections: dict[str, list[dict]] = collections or {}
        self._next_id = 1
        self.requests: list[dict] = []

    def request(self, method: str, url: str, headers: dict, body: bytes | None) -> dict:
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        if method == "GET":
            return {"status": 200, "body": _canon(self._collections.get(path, []))}
        if method == "POST":
            member = dict(json.loads(body or b"{}"))
            member["id"] = self._next_id
            self._next_id += 1
            self._collections.setdefault(path, []).append(member)
            return {"status": 201, "body": _canon(member)}
        if method == "DELETE":
            wanted = path.rsplit("/", 1)[-1]
            for members in self._collections.values():
                members[:] = [m for m in members if str(m.get("id")) != wanted]
            return {"status": 204, "body": b""}
        return {"status": 405, "body": b""}


class ApiEffector:
    """Writes through one service's official API, bounded by that service's declared
    operations, acting only on a gate allow for the exact plan, verified by re-reading
    the resource rather than by believing the response."""

    name = "api-effector"

    def __init__(self, driver: Any, service: ApiService) -> None:
        self._driver = driver
        self._service = service
        self._planned: dict[str, tuple[ApiOperation, dict]] = {}  # plan.digest -> intent (no secret)
        self._prior: dict[str, str] = {}  # plan.digest -> the undo path, resolved at act time

    def bound(self) -> dict:
        """Origin AND intents: both decide how far a gate allow can travel."""
        return {
            "kind": "api",
            "origins": [self._service.origin],
            "intents": sorted(op.intent for op in self._service.operations),
        }

    # --- perception ----------------------------------------------------------

    def perceive(self, target: str) -> Observation:
        """A witnessed read of the resource the action will change. This is the
        before-state, and it is what makes verification possible at all."""
        url = self._url(target)
        response = self._send("GET", url, None)
        members = self._members(response.get("body") or b"")
        return Observation(
            organ=self.name,
            subject=url,
            summary=f"{self._service.name} {target}: {len(members)} members",
            # a read that did not land establishes nothing about the resource
            status=Status.PASS if response.get("status") == 200 else Status.UNVERIFIED,
            provenance=Provenance.witness_bytes(url, _canon(members), "high"),
            data={"url": url, "status": response.get("status"), "members": members,
                  "sha256": sha256_hex(_canon(members))},
        )

    # --- the efferent contract ----------------------------------------------

    def preview(self, target: str, call: ApiCall, before: Observation | None = None) -> Plan:
        """Resolve the intent against the service allowlist and content-address the
        request. No side effect, no credential read, no network."""
        op = self._operation(call.intent)
        if re.fullmatch(op.path_shape, target) is None:
            raise RefusedActuation(
                f"target {target!r} does not match the path shape for intent {call.intent!r}")
        body = _canon(call.body)
        url = self._url(target)
        content_sha = sha256_hex(body)
        digest = "sha256:" + sha256_hex(f"{op.action_kind}|{url}|{content_sha}".encode("utf-8"))
        self._planned[digest] = (op, dict(call.body))
        return Plan(op.action_kind, url, content_sha, op.reversible, False, digest)

    def act(self, plan: Plan, allow_receipt: Any, call: ApiCall) -> Observation:
        """Send the request. Refuses without a gate allow bound to this plan, and
        resolves the credential only here, at the moment of the call."""
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow -- the effector will not call anything")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        op, _ = self._planned.get(plan.digest, (None, None))
        if op is None or op.intent != call.intent:
            raise RefusedActuation("call does not match the previewed (authorized) plan")
        body = _canon(call.body)
        if sha256_hex(body) != plan.content_sha256:
            raise RefusedActuation("request body does not match the previewed (authorized) plan")
        response = self._send(op.method, plan.target, body)
        if op.reversible:
            self._prior[plan.digest] = self._undo_path(op, plan.target, response)
        return self.perceive(self._path(plan.target))

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        """Does the RESOURCE now carry the intent? Re-reads the collection; a 201 on
        the write is not evidence and is never consulted here."""
        op, intent = self._planned.get(plan.digest, (None, None))
        if intent is None:
            return Verdict("failed", "no previewed intent for this plan")
        for member in after.data.get("members", []):
            projection = {k: member.get(k) for k in intent if k in member}
            if projection == intent:
                return Verdict("pass", "resource carries the intent")
        return Verdict("failed", "resource does NOT carry the intent (the write did not land)")

    def rollback(self, plan: Plan) -> Observation:
        """The service's own undo, where it declares one."""
        path = self._prior.get(plan.digest)
        if path is None:
            raise RefusedActuation("no undo recorded for this plan -- the call is irreversible")
        op, _ = self._planned[plan.digest]
        self._send(op.undo_method, self._url(path), None)
        return self.perceive(self._path(plan.target))

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise and send nothing."""
        driver = FakeApiDriver({"/repos/o/r/issues/1/comments": []})
        effector = ApiEffector(driver, GITHUB_ISSUE_COMMENTS)
        call = ApiCall("post_comment", {"body": "hi"})
        plan = effector.preview("/repos/o/r/issues/1/comments", call)
        try:
            effector.act(plan, allow_receipt=None, call=call)
            return False
        except RefusedActuation:
            return not driver.requests

    # --- internals -----------------------------------------------------------

    def _operation(self, intent: str) -> ApiOperation:
        for op in self._service.operations:
            if op.intent == intent:
                return op
        declared = sorted(o.intent for o in self._service.operations)
        raise RefusedActuation(f"intent {intent!r} is not declared by {self._service.name}: {declared}")

    def _url(self, target: str) -> str:
        return target if target.startswith(self._service.origin) else self._service.origin + target

    def _path(self, url: str) -> str:
        return url[len(self._service.origin):] if url.startswith(self._service.origin) else url

    def _members(self, payload: bytes) -> list[dict]:
        try:
            data = json.loads(payload or b"[]")
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            return [data]
        return [m for m in data if isinstance(m, dict)] if isinstance(data, list) else []

    def _undo_path(self, op: ApiOperation, url: str, response: dict) -> str:
        parts = re.fullmatch(op.path_shape, self._path(url))
        created = self._members(response.get("body") or b"")
        ident = created[0].get("id") if created else None
        return op.undo_shape.format(id=ident, **(parts.groupdict() if parts else {}))

    def _send(self, method: str, url: str, body: bytes | None) -> dict:
        """The single place a credential is read, and the single place one leaves."""
        token = require_secret(self._service.auth_env)
        if token in url:
            # the URL is witnessed into the journal; the secret travels in a header only
            raise RefusedActuation("the credential must not appear in the URL; it is sent as a header")
        if not url.startswith(self._service.origin + "/"):
            raise RefusedActuation(f"url {url!r} is outside the service origin {self._service.origin}")
        headers = {"Authorization": f"{self._service.auth_scheme} {token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        return self._driver.request(method, url, headers, body)
