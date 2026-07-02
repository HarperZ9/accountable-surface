"""Optional real headless-browser backend for `BrowserEffector` -- Playwright/Chromium.

This is the ONLY place a browser binary enters the picture, and it is entirely
optional: Playwright is imported lazily (on instantiation), so the default install
and the whole test suite stay zero-dependency. Install the extra only when you want
to drive a live JS-capable page:

    pip install "accountable-surface[browser]"
    python -m playwright install chromium

It wraps async Playwright behind the synchronous `BrowserDriver` protocol so it is a
drop-in for `FakeBrowserDriver`. The accountability logic (gate, verify, rollback,
journal) is driver-agnostic -- swapping the stub for this backend changes nothing
about the contract, only where the page lives.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Accessible-name extraction, run in the page. Mirrors HttpDriver's rule (a
# <label for>, else aria-label / name / placeholder / id) so the same accessible
# labels address fields whether the page is server-rendered or a live SPA.
_FIELDS_JS = """() => {
  const out = {};
  const labelFor = {};
  document.querySelectorAll('label[for]').forEach(l => {
    labelFor[l.getAttribute('for')] = (l.textContent || '').trim();
  });
  document.querySelectorAll('input, textarea, select').forEach(el => {
    const name = labelFor[el.id] || el.getAttribute('aria-label')
      || el.getAttribute('name') || el.getAttribute('placeholder') || el.id;
    if (name) out[name] = el.value || '';
  });
  return out;
}"""


class PlaywrightDriver:
    """Real headless Chromium via Playwright, presented through the synchronous
    `BrowserDriver` protocol. Optional + lazily imported -- never a hard dependency."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = 5000, start: str = "about:blank") -> None:
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise ImportError(
                "Playwright is not installed. Install the optional browser backend with:\n"
                '  pip install "accountable-surface[browser]"\n'
                "  python -m playwright install chromium"
            ) from exc
        self._headless = headless
        self._timeout = timeout_ms
        self._url = start
        self._history: list[str] = []
        self._last_eval: Any = None
        self._loop = asyncio.new_event_loop()
        self._playwright = None
        self._browser = None
        self._page = None

    # --- lifecycle -----------------------------------------------------------

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    async def _ensure_page(self):
        if self._page is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            self._page = await self._browser.new_page()
            self._page.set_default_timeout(self._timeout)
        return self._page

    def close(self) -> None:
        async def _shutdown():
            if self._page is not None:
                await self._browser.close()
                await self._playwright.stop()

        if self._page is not None:
            self._run(_shutdown())
            self._page = self._browser = self._playwright = None
        if not self._loop.is_closed():
            self._loop.close()

    # --- BrowserDriver protocol ----------------------------------------------

    def current_url(self) -> str:
        return self._url

    def navigate(self, url: str) -> None:
        async def _go():
            page = await self._ensure_page()
            await page.goto(url, wait_until="networkidle")
            return page.url

        self._history.append(self._url)
        self._url = self._run(_go())

    def back(self) -> None:
        async def _back():
            page = await self._ensure_page()
            await page.go_back(wait_until="networkidle")
            return page.url

        self._url = self._run(_back())
        if self._history:
            self._history.pop()

    def click(self, selector: str) -> None:
        async def _click():
            page = await self._ensure_page()
            # Click by accessible role/name first, falling back to visible text.
            try:
                await page.get_by_text(selector, exact=True).first.click()
            except Exception:  # noqa: BLE001 - broad: any locator/timeout falls back
                await page.click(f"text={selector}")
            await page.wait_for_load_state("networkidle")
            return page.url

        self._history.append(self._url)
        self._url = self._run(_click())

    def fill(self, selector: str, value: str) -> None:
        async def _fill():
            page = await self._ensure_page()
            await page.get_by_label(selector).fill(value)

        self._run(_fill())

    def evaluate(self, script: str) -> Any:
        async def _eval():
            page = await self._ensure_page()
            return await page.evaluate(script)

        self._last_eval = self._run(_eval())
        return self._last_eval

    def field_value(self, selector: str):
        return self.snapshot().get("fields", {}).get(selector)

    def snapshot(self) -> dict:
        async def _snap():
            page = await self._ensure_page()
            return page.url, await page.title(), await page.evaluate(_FIELDS_JS)

        url, title, fields = self._run(_snap())
        self._url = url
        return {"url": url, "title": title, "fields": fields, "last_eval": self._last_eval}
