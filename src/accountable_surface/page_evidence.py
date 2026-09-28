"""Structured page evidence: what the policy check and the readback read.

`HttpDriver` keeps a page's title and its fields, which is enough to act. The policy
check needs more: every control with its role, accessible name, input type and
autocomplete hint, whether a button submits a form, the frames on the page, the
class and id tokens a challenge widget carries, the visible text, and the HTTP
status with the headers a challenge answer sets. This module reads that from the
HTML and nothing else. It runs no script, loads no frame, fetches no subresource,
and clicks nothing.

`capture` is the independent reader for a page served over http(s): a plain GET
with an honest User-Agent, separate from the driver that acts. Accessible names
follow the same order `HttpDriver` uses (label, aria-label, name, placeholder,
id), so a step that names a field by the name the driver fills finds the same
control here.

Limit: hidden elements and CSS are not evaluated, so text a browser would hide
still counts as visible text. That can only add hits to a detector, never remove
one.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser

SCHEMA = "accountable-surface.page-evidence/v1"
IDENTITY = "accountable-surface (automated; policy readback)"
MAX_TEXT = 20_000
MAX_MARKERS = 2_000
KEPT_HEADERS = ("content-type", "cf-mitigated", "location")
TEXTBOX_TYPES = frozenset({
    "", "text", "email", "password", "search", "tel", "url", "number", "date",
    "datetime-local", "month", "week", "time",
})
BUTTON_TYPES = frozenset({"submit", "image", "button", "reset"})
KEPT_ATTRS = ("id", "name", "autocomplete", "placeholder", "aria-label", "type", "class", "title")
_SKIP_TEXT = frozenset({"script", "style", "noscript", "template"})


@dataclass(frozen=True)
class Control:
    """One actionable element as a screen reader would name it."""

    ref: str
    tag: str
    role: str
    name: str
    input_type: str
    attrs: tuple[tuple[str, str], ...]
    in_form: bool
    form_action: str

    def attr(self, key: str) -> str:
        return dict(self.attrs).get(key, "")

    def to_dict(self) -> dict:
        return {"ref": self.ref, "tag": self.tag, "role": self.role, "name": self.name,
                "input_type": self.input_type, "attrs": dict(self.attrs),
                "in_form": self.in_form, "form_action": self.form_action}


@dataclass(frozen=True)
class PageEvidence:
    url: str
    http_status: int
    headers: tuple[tuple[str, str], ...]
    title: str
    controls: tuple[Control, ...]
    frames: tuple[tuple[str, str], ...]  # (src, title)
    markers: tuple[str, ...]  # class and id tokens, data-sitekey presence
    text: str
    redactions: int = 0
    channel: str = "html-parse"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def origin(self) -> str:
        return origin_of(self.url)

    def header(self, key: str) -> str:
        return dict(self.headers).get(key.lower(), "")

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "url": self.url, "http_status": self.http_status,
                "headers": dict(self.headers), "title": self.title,
                "controls": [c.to_dict() for c in self.controls],
                "frames": [list(f) for f in self.frames], "markers": list(self.markers),
                "text": self.text, "redactions": self.redactions, "channel": self.channel}

    @property
    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()

    def find(self, control: dict | None) -> Control | None:
        """Resolve a step's control by ref, else by exact name (and role, when given).
        A name two controls share resolves to nothing: ambiguity settles no target."""
        if not isinstance(control, dict):
            return None
        if control.get("ref"):
            return next((c for c in self.controls if c.ref == control["ref"]), None)
        name, role = control.get("name"), control.get("role")
        hits = [c for c in self.controls if c.name == name and (not role or c.role == role)]
        return hits[0] if len(hits) == 1 else None


def origin_of(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else ""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self._in_title, self._skip = "", False, 0
        self.labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self.raw: list[dict] = []
        self._open: dict | None = None  # a button or link collecting its text
        self._forms: list[str] = []
        self.frames: list[tuple[str, str]] = []
        self.markers: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self._markers(a)
        if tag in _SKIP_TEXT:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "form":
            self._forms.append(a.get("action", ""))
        elif tag == "label":
            self._label_for, self._label_text = a.get("for"), []
        elif tag in ("input", "textarea", "select"):
            self._control(tag, a)
        elif tag in ("button",) or (tag == "a" and "href" in a):
            self._open = {"tag": tag, "a": a, "text": [], "in_form": bool(self._forms),
                          "form_action": self._forms[-1] if self._forms else ""}
        elif tag == "iframe":
            self.frames.append((a.get("src", ""), a.get("title", "")))

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "form" and self._forms:
            self._forms.pop()
        elif tag == "label" and self._label_for:
            self.labels[self._label_for] = " ".join("".join(self._label_text).split())
            self._label_for = None
        elif self._open is not None and tag == self._open["tag"]:
            self.raw.append(self._open)
            self._open = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._label_for is not None:
            self._label_text.append(data)
        if self._open is not None:
            self._open["text"].append(data)
        self.text.append(data)

    def _control(self, tag, a):
        if tag == "input" and a.get("type", "").lower() == "hidden":
            return
        self.raw.append({"tag": tag, "a": a, "text": [], "in_form": bool(self._forms),
                         "form_action": self._forms[-1] if self._forms else ""})

    def _markers(self, a):
        if len(self.markers) >= MAX_MARKERS:
            return
        self.markers += [t.lower() for t in a.get("class", "").split()]
        for key in ("id", "name"):
            if a.get(key):
                self.markers.append(a[key].lower())
        if "data-sitekey" in a:
            self.markers.append("data-sitekey")


def _role(tag: str, input_type: str) -> str:
    if tag == "textarea":
        return "textbox"
    if tag == "select":
        return "combobox"
    if tag == "a":
        return "link"
    if tag == "button" or input_type in BUTTON_TYPES:
        return "button"
    if input_type in ("checkbox", "radio", "file"):
        return input_type
    return "textbox" if input_type in TEXTBOX_TYPES else input_type


def _name(raw: dict, labels: dict[str, str]) -> str:
    a, text = raw["a"], " ".join("".join(raw["text"]).split())
    if raw["tag"] in ("button", "a"):
        return a.get("aria-label") or text or a.get("value", "")
    if a.get("type", "").lower() in BUTTON_TYPES:
        return a.get("aria-label") or a.get("value", "") or "Submit"
    return (labels.get(a.get("id", ""), "") or a.get("aria-label") or a.get("name")
            or a.get("placeholder") or a.get("id") or "")


def _controls(parser: _PageParser) -> tuple[Control, ...]:
    out = []
    for index, raw in enumerate(parser.raw):
        a = raw["a"]
        input_type = a.get("type", "").lower() if raw["tag"] == "input" else (
            a.get("type", "submit").lower() if raw["tag"] == "button" else "")
        role = _role(raw["tag"], input_type)
        name = _name(raw, parser.labels)
        attrs = tuple((k, a[k]) for k in KEPT_ATTRS if a.get(k))
        out.append(Control(f"c{index}:{role}:{name}", raw["tag"], role, name, input_type,
                           attrs, raw["in_form"], raw["form_action"]))
    return tuple(out)


def parse_page(url: str, html: str, *, http_status: int = 200, response_headers: dict | None = None,
               channel: str = "html-parse", redactor=None) -> PageEvidence:
    """Parse HTML into evidence. `redactor(text) -> (text, count)` runs over the
    visible text before it is kept, so a secret shape on screen is never stored."""
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    text = " ".join(" ".join(parser.text).split())[:MAX_TEXT]
    redactions = 0
    if redactor is not None:
        text, redactions = redactor(text)
    kept = tuple(sorted((k.lower(), str(v)) for k, v in (response_headers or {}).items() if k.lower() in KEPT_HEADERS))
    return PageEvidence(url=url, http_status=int(http_status), headers=kept,
                        title=" ".join(parser.title.split()), controls=_controls(parser),
                        frames=tuple(parser.frames), markers=tuple(parser.markers),
                        text=text, redactions=redactions, channel=channel)


def capture(url: str, *, timeout: float = 10.0, max_bytes: int = 2_000_000, redactor=None) -> PageEvidence:
    """GET the page with a plain, honest request and parse it. An HTTP error status
    is evidence too (a challenge often arrives as a 403 or 503), so it is parsed,
    not raised."""
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError(f"unsupported scheme for readback: {url!r}")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": IDENTITY})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (scheme checked)
            body, status = response.read(max_bytes), response.status
            headers, final = dict(response.headers.items()), response.geturl()
    except urllib.error.HTTPError as exc:
        body, status, headers, final = exc.read(max_bytes), exc.code, dict(exc.headers.items()), url
    html = body.decode("utf-8", errors="replace")
    return parse_page(final, html, http_status=status, response_headers=headers,
                      channel="http-get", redactor=redactor)
