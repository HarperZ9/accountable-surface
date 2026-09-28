"""Live-suite fixtures: a real headless Chromium through PlaywrightDriver, and the
local fixture site on 127.0.0.1. Nothing here reaches beyond the machine, and
no everyday browser profile is used: Playwright launches its own Chromium with
a fresh, temporary profile.

A live test that cannot get its browser skips with a named reason; it never
passes silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the shared test helpers

from actuation_site import Site  # noqa: E402

MUTATING = ("navigate", "back", "click", "fill", "evaluate")


def _spy_class():
    from accountable_surface.playwright_driver import PlaywrightDriver

    class SpyBrowser(PlaywrightDriver):
        """The real driver, recording every call that can change the page."""

        def __init__(self, **kw):
            super().__init__(**kw)
            self.calls: list[str] = []

        def navigate(self, url):
            self.calls.append(f"navigate {url}")
            super().navigate(url)

        def back(self):
            self.calls.append("back")
            super().back()

        def click(self, selector):
            self.calls.append(f"click {selector}")
            super().click(selector)

        def fill(self, selector, value):
            self.calls.append(f"fill {selector}")
            super().fill(selector, value)

        def evaluate(self, script):
            self.calls.append("evaluate")
            return super().evaluate(script)

    return SpyBrowser


@pytest.fixture
def chromium():
    try:
        driver = _spy_class()(timeout_ms=15000)
        driver._run(driver._ensure_page())
    except ImportError as exc:
        pytest.skip(f"live browser: Playwright is not installed ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - any launch failure is a named skip, not a pass
        pytest.skip(f"live browser: Chromium did not launch ({type(exc).__name__}: {str(exc)[:120]})")
    yield driver
    driver.close()


@pytest.fixture
def site():
    s = Site().start()
    yield s
    s.stop()


@pytest.fixture
def other_site():
    s = Site().start()
    yield s
    s.stop()
