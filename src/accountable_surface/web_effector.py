"""Native web actuation for the efferent arm — act on the page's STRUCTURE (navigate,
fill by accessible label), NOT pixels, under the same Effector contract.

**Zero external dependencies, by design.** This is a native ecosystem meant to
SURPASS heavyweight browser-automation deps (Playwright/Chromium), not depend on
them: the accountability logic is driver-agnostic, and the real backend is a native
stdlib HTTP/HTML driver (`urllib` + `html.parser`, reusing the witnessed web organ)
— no browser binary for server-rendered pages. `FakePageDriver` makes the whole
contract deterministically testable offline. Acting by accessible label is both more
robust than screenshot-driving and inherently accessible — the path a screen-reader
user takes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex

from accountable_surface.effector import Plan, RefusedActuation, Verdict


@dataclass(frozen=True)
class WebAction:
    """A semantic action on the accessibility tree — never a pixel coordinate."""

    kind: str  # "navigate" | "fill" | "submit"
    url: str = ""  # navigate: destination; fill: the page; submit: the POST/action url
    selector: str = ""  # fill: the field's accessible name / label
    value: str = ""  # fill: the value to enter; submit: the expected response title


def _canon(snapshot: dict) -> bytes:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FakePageDriver:
    """Deterministic in-memory page model for tests + offline demos."""

    def __init__(self, pages: dict[str, dict] | None = None, start: str = "about:blank") -> None:
        self._pages = pages or {start: {"title": start, "fields": {}}}
        self._url = start
        self._history: list[str] = []

    def current_url(self) -> str:
        return self._url

    def navigate(self, url: str) -> None:
        self._history.append(self._url)
        self._url = url
        self._pages.setdefault(url, {"title": url, "fields": {}})

    def back(self) -> None:
        if self._history:
            self._url = self._history.pop()

    def submit(self, url: str, data: dict) -> None:
        """Submit form data and land on the result page (the form's action url)."""
        self.navigate(url)

    def fill(self, selector: str, value: str) -> None:
        self._pages.setdefault(self._url, {"title": self._url, "fields": {}})
        self._pages[self._url]["fields"][selector] = value

    def field_value(self, selector: str) -> str | None:
        return self._pages.get(self._url, {}).get("fields", {}).get(selector)

    def snapshot(self) -> dict:
        page = self._pages.get(self._url, {"title": "", "fields": {}})
        return {"url": self._url, "title": page.get("title", ""), "fields": dict(page.get("fields", {}))}


class WebEffector:
    """Acts on a page's structure / accessibility tree (navigate / fill), bounded to
    allowed origins, only on a gate allow, and verified by re-snapshotting. Native:
    a `FakePageDriver` (offline) or a stdlib HTTP/HTML driver — never a browser dep."""

    name = "web-effector"

    def __init__(self, driver: Any, allowed_origins: list[str]) -> None:
        self._driver = driver
        self._origins = [o.rstrip("/") for o in allowed_origins]
        self._prior: dict[str, Any] = {}  # plan.digest -> rollback info

    # --- perception ----------------------------------------------------------

    def perceive(self, target: str = "") -> Observation:
        """Witnessed snapshot of the current page's structure (the a11y tree)."""
        snap = self._driver.snapshot()
        url = snap.get("url", target)
        return Observation(
            organ=self.name,
            subject=f"dom://{url}",
            summary=f"page {url!r}: {len(snap.get('fields', {}))} fields",
            status=Status.PASS,
            provenance=Provenance.witness_bytes(f"dom://{url}", _canon(snap), "high"),
            data={"url": url, "title": snap.get("title"), "fields": snap.get("fields", {})},
        )

    # --- the efferent contract ----------------------------------------------

    def preview(self, target: str, action: WebAction, before: Observation | None = None) -> Plan:
        action_kind = f"web.{action.kind}"
        if action.kind == "navigate":
            post_target, content_sha, reversible = action.url, sha256_hex(action.url.encode("utf-8")), True
        elif action.kind == "fill":
            post_target = f"{action.url}#{action.selector}"
            content_sha, reversible = sha256_hex(action.value.encode("utf-8")), True
        elif action.kind == "submit":
            # a POST mutates server state — irreversible (escalates unless pre-authorized)
            post_target, content_sha, reversible = action.url, sha256_hex(action.value.encode("utf-8")), False
        else:
            raise RefusedActuation(f"unsupported web action: {action.kind!r}")
        digest = "sha256:" + sha256_hex(f"{action_kind}|{post_target}|{content_sha}".encode("utf-8"))
        existed = bool((before.data.get("fields", {}) if before else {}).get(action.selector))
        return Plan(action_kind, post_target, content_sha, reversible, existed, digest)

    def act(self, plan: Plan, allow_receipt: Any, action: WebAction) -> Observation:
        """Perform the action — only on a gate allow for THIS plan, only within the
        allowed origins. Records rollback info. Returns a witnessed post-snapshot."""
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow — the effector will not act")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        if not self._within_origin(action.url):
            raise RefusedActuation(f"url origin is outside the allowed origins: {self._origins}")
        if action.kind == "navigate":
            self._prior[plan.digest] = ("navigate",)
            self._driver.navigate(action.url)
        elif action.kind == "fill":
            if self._driver.current_url() != action.url:
                raise RefusedActuation("not on the target page — navigate (accountably) first")
            self._prior[plan.digest] = ("fill", action.selector, self._driver.field_value(action.selector))
            self._driver.fill(action.selector, action.value)
        elif action.kind == "submit":
            self._prior[plan.digest] = ("submit",)
            self._driver.submit(action.url, dict(self._driver.snapshot().get("fields", {})))
        return self.perceive(plan.target)

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        """Re-perceive and check the post-condition (proprioception)."""
        if plan.action_kind == "web.navigate":
            ok = (after.data.get("url") or "").rstrip("/") == plan.target.rstrip("/")
            return Verdict("pass" if ok else "failed", "url " + ("matches" if ok else "does NOT match"))
        if plan.action_kind == "web.fill":
            selector = plan.target.split("#", 1)[1] if "#" in plan.target else ""
            value = after.data.get("fields", {}).get(selector)
            ok = value is not None and sha256_hex(str(value).encode("utf-8")) == plan.content_sha256
            return Verdict("pass" if ok else "failed", "field " + ("holds intent" if ok else "does NOT hold intent"))
        if plan.action_kind == "web.submit":
            title = after.data.get("title") or ""
            ok = sha256_hex(title.encode("utf-8")) == plan.content_sha256
            return Verdict("pass" if ok else "failed", "response " + ("matches intent" if ok else "does NOT match intent"))
        return Verdict("failed", "unknown action kind")

    def rollback(self, plan: Plan) -> Observation:
        info = self._prior.get(plan.digest)
        if info is None:
            raise RefusedActuation("no rollback info recorded for this plan")
        if info[0] == "navigate":
            self._driver.back()
        elif info[0] == "fill":
            _, selector, prior = info
            self._driver.fill(selector, prior if prior is not None else "")
        elif info[0] == "submit":
            raise RefusedActuation("submit is irreversible — nothing to roll back")
        return self.perceive(plan.target)

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise and not navigate."""
        driver = FakePageDriver(start="https://ok.test/")
        effector = WebEffector(driver, allowed_origins=["https://ok.test"])
        action = WebAction("navigate", url="https://ok.test/page")
        plan = effector.preview("https://ok.test/", action)
        try:
            effector.act(plan, allow_receipt=None, action=action)
            return False
        except RefusedActuation:
            return driver.current_url() == "https://ok.test/"

    # --- internals -----------------------------------------------------------

    def _within_origin(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return origin in self._origins
