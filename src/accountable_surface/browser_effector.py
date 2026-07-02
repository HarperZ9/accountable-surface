"""JavaScript-capable browser actuation for the efferent arm.

`WebEffector` (native stdlib HTTP/HTML) runs zero JavaScript, so single-page apps
are out of reach. `BrowserEffector` closes that gap: it drives a live, JS-capable
page (execute JS, click by accessible label, follow cross-origin navigation) under
the SAME Effector contract -- inert until authorized, origin-bounded, verified by
re-perceiving, reversible-or-escalate.

The browser backend is INJECTABLE via the `BrowserDriver` protocol. A deterministic
`FakeBrowserDriver` (zero-dep, offline) makes the whole contract testable and is used
by the entire suite. The real headless-Chromium backend (`PlaywrightDriver`) is an
optional, lazily imported dependency (`accountable-surface[browser]`) -- wired only
when explicitly requested, never required for the tests to pass.

Acting by accessible label (not pixel coordinates) is both more robust than
screenshot-driving and inherently accessible -- the path a screen-reader user takes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex

from accountable_surface.effector import Plan, RefusedActuation, Verdict


@dataclass(frozen=True)
class BrowserAction:
    """A semantic action on the accessibility tree -- never a pixel coordinate."""

    kind: str  # "navigate" | "click" | "fill" | "evaluate"
    url: str = ""  # the page the action targets (navigate: destination)
    selector: str = ""  # click/fill: the accessible label / name
    value: str = ""  # fill: the value; evaluate: the JS source


@runtime_checkable
class BrowserDriver(Protocol):
    """A JS-capable page-automation backend. Perceive the DOM accessibility tree,
    act by label, run JS, and follow cross-origin navigation. `FakeBrowserDriver`
    is the deterministic in-memory implementation; `PlaywrightDriver` is the real
    headless one."""

    def current_url(self) -> str: ...
    def navigate(self, url: str) -> None: ...
    def back(self) -> None: ...
    def click(self, selector: str) -> None: ...
    def fill(self, selector: str, value: str) -> None: ...
    def evaluate(self, script: str) -> Any: ...
    def field_value(self, selector: str) -> str | None: ...
    def snapshot(self) -> dict: ...


def _canon(snapshot: dict) -> bytes:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FakeBrowserDriver:
    """Deterministic in-memory SPA model for tests + offline demos -- zero-dep.

    A page may declare `clicks`: a map of accessible label -> destination URL, so a
    click can trigger a client-side navigation (the SPA behaviour `HttpDriver` cannot
    reproduce). `evaluate` supports a tiny deterministic subset (`document.title`);
    any other script is a no-op that returns None, which is enough to prove the
    accountability contract without a real JS engine."""

    def __init__(self, pages: dict[str, dict] | None = None, start: str = "about:blank") -> None:
        self._pages = pages or {start: {"title": start, "fields": {}}}
        self._url = start
        self._history: list[str] = []
        self._last_eval: Any = None

    def current_url(self) -> str:
        return self._url

    def navigate(self, url: str) -> None:
        self._history.append(self._url)
        self._url = url
        self._pages.setdefault(url, {"title": url, "fields": {}})

    def back(self) -> None:
        if self._history:
            self._url = self._history.pop()

    def click(self, selector: str) -> None:
        """Fire a click by accessible label. If the label maps to a client-side
        navigation, follow it; otherwise the click is inert (no page change)."""
        page = self._pages.get(self._url, {})
        destination = page.get("clicks", {}).get(selector)
        if destination is not None:
            self.navigate(destination)

    def fill(self, selector: str, value: str) -> None:
        self._pages.setdefault(self._url, {"title": self._url, "fields": {}})
        self._pages[self._url].setdefault("fields", {})[selector] = value

    def evaluate(self, script: str) -> Any:
        page = self._pages.get(self._url, {})
        self._last_eval = page.get("title", "") if script.strip() == "document.title" else None
        return self._last_eval

    def field_value(self, selector: str) -> str | None:
        return self._pages.get(self._url, {}).get("fields", {}).get(selector)

    def snapshot(self) -> dict:
        page = self._pages.get(self._url, {"title": "", "fields": {}})
        return {
            "url": self._url,
            "title": page.get("title", ""),
            "fields": dict(page.get("fields", {})),
            "last_eval": self._last_eval,
        }


class BrowserEffector:
    """Acts on a live JS-capable page (navigate / click / fill / evaluate), bounded to
    a set of allowed origins, only on a gate allow for THIS exact plan, and verified
    by re-perceiving the accessibility tree. Driver-agnostic: inject `FakeBrowserDriver`
    (offline, deterministic) for tests or `PlaywrightDriver` (real headless) in
    production. Same perceive -> plan -> act -> verify -> rollback contract as
    `FilesystemEffector` and `WebEffector`."""

    name = "browser-effector"

    def __init__(self, driver: Any, allowed_origins: list[str]) -> None:
        self._driver = driver
        self._origins = [o.rstrip("/") for o in allowed_origins]
        self._prior: dict[str, Any] = {}  # plan.digest -> rollback info

    # --- perception ----------------------------------------------------------

    def perceive(self, target: str = "") -> Observation:
        """Witnessed snapshot of the current page's accessibility tree."""
        snap = self._driver.snapshot()
        url = snap.get("url", target)
        return Observation(
            organ=self.name,
            subject=f"dom://{url}",
            summary=f"page {url!r}: {len(snap.get('fields', {}))} fields",
            status=Status.PASS,
            provenance=Provenance.witness_bytes(f"dom://{url}", _canon(snap), "high"),
            data={
                "url": url,
                "title": snap.get("title"),
                "fields": snap.get("fields", {}),
                "last_eval": snap.get("last_eval"),
                "page_digest": sha256_hex(_canon(snap)),
            },
        )

    # --- the efferent contract ----------------------------------------------

    def preview(self, target: str, action: BrowserAction, before: Observation | None = None) -> Plan:
        action_kind = f"browser.{action.kind}"
        if action.kind == "navigate":
            post_target, content_sha, reversible = action.url, sha256_hex(action.url.encode("utf-8")), True
        elif action.kind == "click":
            post_target = f"{action.url}#{action.selector}"
            content_sha, reversible = sha256_hex(action.selector.encode("utf-8")), True
        elif action.kind == "fill":
            post_target = f"{action.url}#{action.selector}"
            content_sha, reversible = sha256_hex(action.value.encode("utf-8")), True
        elif action.kind == "evaluate":
            # a script's side effects cannot be undone -- irreversible (escalates).
            post_target = f"{action.url}!js"
            content_sha, reversible = sha256_hex(action.value.encode("utf-8")), False
        else:
            raise RefusedActuation(f"unsupported browser action: {action.kind!r}")
        digest = "sha256:" + sha256_hex(f"{action_kind}|{post_target}|{content_sha}".encode("utf-8"))
        existed = bool((before.data.get("fields", {}) if before else {}).get(action.selector))
        return Plan(action_kind, post_target, content_sha, reversible, existed, digest)

    def act(self, plan: Plan, allow_receipt: Any, action: BrowserAction) -> Observation:
        """Perform the action -- only on a gate allow for THIS plan, only within the
        allowed origins. Records rollback info. Returns a witnessed post-snapshot."""
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow -- the effector will not act")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        if not self._within_origin(action.url):
            raise RefusedActuation(f"url origin is outside the allowed origins: {self._origins}")
        before_digest = self.perceive(plan.target).data.get("page_digest")
        self._dispatch(plan, action, before_digest)
        return self.perceive(plan.target)

    def _dispatch(self, plan: Plan, action: BrowserAction, before_digest: str | None) -> None:
        """Execute the concrete driver call and stash the rollback record."""
        if action.kind == "navigate":
            self._prior[plan.digest] = ("navigate", before_digest)
            self._driver.navigate(action.url)
        elif action.kind == "click":
            if self._driver.current_url() != action.url:
                raise RefusedActuation("not on the target page -- navigate (accountably) first")
            self._prior[plan.digest] = ("click", before_digest)
            self._driver.click(action.selector)
            # A click can fire a client-side handler that navigates ANYWHERE the page
            # declares -- the origin bound must hold for the click's DESTINATION, not
            # just the page it was dispatched from. If it escaped the allowlist, undo
            # the navigation and refuse (the bound is a second gate, stricter than any
            # grant), so the surface reports refused-by-effector and the page stays put.
            landed = self._driver.current_url()
            if not self._within_origin(landed):
                self._driver.back()
                del self._prior[plan.digest]
                raise RefusedActuation(
                    f"click navigated off the allowed origins {self._origins}: {landed!r}"
                )
        elif action.kind == "fill":
            if self._driver.current_url() != action.url:
                raise RefusedActuation("not on the target page -- navigate (accountably) first")
            self._prior[plan.digest] = ("fill", action.selector, self._driver.field_value(action.selector))
            self._driver.fill(action.selector, action.value)
        elif action.kind == "evaluate":
            self._prior[plan.digest] = ("evaluate",)
            self._driver.evaluate(action.value)

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        """Re-perceive and check the post-condition (proprioception)."""
        if plan.action_kind == "browser.navigate":
            ok = (after.data.get("url") or "").rstrip("/") == plan.target.rstrip("/")
            return Verdict("pass" if ok else "failed", "url " + ("matches" if ok else "does NOT match"))
        if plan.action_kind == "browser.click":
            prior = self._prior.get(plan.digest, (None, None))
            before_digest = prior[1] if len(prior) > 1 else None
            ok = after.data.get("page_digest") != before_digest
            return Verdict("pass" if ok else "failed", "click " + ("changed the page" if ok else "had NO effect"))
        if plan.action_kind == "browser.fill":
            selector = plan.target.split("#", 1)[1] if "#" in plan.target else ""
            value = after.data.get("fields", {}).get(selector)
            ok = value is not None and sha256_hex(str(value).encode("utf-8")) == plan.content_sha256
            return Verdict("pass" if ok else "failed", "field " + ("holds intent" if ok else "does NOT hold intent"))
        if plan.action_kind == "browser.evaluate":
            ran = after.data.get("last_eval") is not None
            return Verdict("pass" if ran else "failed", "script " + ("ran" if ran else "returned nothing"))
        return Verdict("failed", "unknown action kind")

    def rollback(self, plan: Plan) -> Observation:
        info = self._prior.get(plan.digest)
        if info is None:
            raise RefusedActuation("no rollback info recorded for this plan")
        if info[0] in ("navigate", "click"):
            self._driver.back()
        elif info[0] == "fill":
            _, selector, prior = info
            self._driver.fill(selector, prior if prior is not None else "")
        elif info[0] == "evaluate":
            raise RefusedActuation("script evaluation is irreversible -- nothing to roll back")
        return self.perceive(plan.target)

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise and not navigate."""
        driver = FakeBrowserDriver(start="https://ok.test/")
        effector = BrowserEffector(driver, allowed_origins=["https://ok.test"])
        action = BrowserAction("navigate", url="https://ok.test/app")
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
