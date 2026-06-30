"""Native HTTP/HTML page driver for `WebEffector` -- stdlib `html.parser` plus the
witnessed clean GET from the coherence-membrane web organ. No browser binary; for
server-rendered pages.

`navigate` = GET + parse the form structure (fields keyed by accessible name);
`fill` = stage a client-side value; `snapshot` = the page structure with staged
values applied. A redirect that changes the URL simply fails `WebEffector.verify`
(the post-condition "I am at the intended URL" is false) -- the accountable outcome.
Drop-in for `FakePageDriver`.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from html.parser import HTMLParser

from coherence_membrane.organs.web import fetch_url


class _FormParser(HTMLParser):
    """Extract the page title and form fields keyed by accessible name (a <label for>,
    else aria-label / name / placeholder / id)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self._inputs: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attr = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "label":
            self._label_for = attr.get("for")
            self._label_text = []
        elif tag in ("input", "textarea", "select"):
            self._inputs.append(attr)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "label" and self._label_for:
            self._labels[self._label_for] = "".join(self._label_text).strip()
            self._label_for = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._label_for is not None:
            self._label_text.append(data)

    def fields(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for attr in self._inputs:
            name = (
                self._labels.get(attr.get("id", ""))
                or attr.get("aria-label")
                or attr.get("name")
                or attr.get("placeholder")
                or attr.get("id")
            )
            if name:
                out[name] = attr.get("value", "")
        return out


def parse_html(url: str, html: str) -> dict:
    """Parse server-rendered HTML into {url, title, fields} (fields by accessible name)."""
    parser = _FormParser()
    parser.feed(html)
    return {"url": url, "title": parser.title.strip(), "fields": parser.fields()}


def post_form(url: str, data: dict, *, timeout: float = 10.0, max_bytes: int = 5_000_000) -> tuple[bytes, dict]:
    """Native stdlib form POST (http/https only, bounded) -- mirrors the web organ's
    clean-fetch discipline on the write side. Returns (payload, meta)."""
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError(f"unsupported scheme for: {url!r}")
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"User-Agent": "accountable-surface/0.1 (native)",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (scheme checked)
        payload = response.read(max_bytes + 1)[:max_bytes]
        status = getattr(response, "status", None) or response.getcode()
        final_url = response.geturl()
    return payload, {"http_status": int(status), "final_url": final_url, "bytes": len(payload)}


class HttpDriver:
    """Native page driver: GET via the witnessed clean fetch, parse the structure,
    stage client-side fills. A drop-in for `FakePageDriver` in `WebEffector`."""

    def __init__(self, *, timeout: float = 10.0, max_bytes: int = 5_000_000, start: str = "about:blank") -> None:
        self._url = start
        self._timeout = timeout
        self._max = max_bytes
        self._history: list[str] = []
        self._parsed: dict = {"url": start, "title": "", "fields": {}}
        self._staged: dict[str, str] = {}

    def current_url(self) -> str:
        return self._url

    def navigate(self, url: str) -> None:
        parsed = self._load(url)
        self._history.append(self._url)
        self._url = parsed["url"]
        self._parsed = parsed
        self._staged = {}

    def back(self) -> None:
        if not self._history:
            return
        self._parsed = self._load(self._history.pop())
        self._url = self._parsed["url"]
        self._staged = {}

    def submit(self, url: str, data: dict) -> None:
        """POST form data and load the response as the new page."""
        payload, meta = post_form(url, data, timeout=self._timeout, max_bytes=self._max)
        html = payload.decode("utf-8", errors="replace")
        self._history.append(self._url)
        self._parsed = parse_html(meta.get("final_url", url), html)
        self._url = self._parsed["url"]
        self._staged = {}

    def fill(self, selector: str, value: str) -> None:
        self._staged[selector] = value

    def field_value(self, selector: str):
        if selector in self._staged:
            return self._staged[selector]
        return self._parsed.get("fields", {}).get(selector)

    def snapshot(self) -> dict:
        fields = dict(self._parsed.get("fields", {}))
        fields.update(self._staged)
        return {"url": self._url, "title": self._parsed.get("title", ""), "fields": fields}

    def _load(self, url: str) -> dict:
        payload, meta = fetch_url(url, timeout=self._timeout, max_bytes=self._max)
        html = payload.decode("utf-8", errors="replace")
        return parse_html(meta.get("final_url", url), html)
