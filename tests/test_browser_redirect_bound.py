"""A navigation that a server redirects off the allowed origins is refused.

`navigate` pre-checks the URL it is asked to open, but a server can answer that
URL with a redirect anywhere. The origin bound must hold for where the page
LANDS, as it already does for a click: the effector goes back and refuses, so
the surface reports refused-by-effector and the page stays put. The live suite
repeats this against a real redirect on 127.0.0.1.
"""

from __future__ import annotations

from test_browser_integrity import _grant

from accountable_surface.browser_effector import BrowserAction, BrowserEffector, FakeBrowserDriver
from accountable_surface.surface import AccountableSurface


class RedirectingDriver(FakeBrowserDriver):
    """A fake whose server answers some URLs with a redirect."""

    def __init__(self, redirects, **kw):
        super().__init__(**kw)
        self.redirects = redirects

    def navigate(self, url):
        super().navigate(self.redirects.get(url, url))


def test_a_redirect_off_the_allowlist_is_refused_and_rolled_back():
    drv = RedirectingDriver({"https://app.test/leave": "https://evil.test/landing"},
                            pages={"https://app.test/": {"title": "Home", "fields": {}}}, start="https://app.test/")
    eff = BrowserEffector(drv, allowed_origins=["https://app.test"])
    out = AccountableSurface().actuate(eff, target="https://app.test/leave",
                                       content=BrowserAction("navigate", url="https://app.test/leave"),
                                       authorization=_grant(["browser.navigate"]))
    assert out.acted is False and out.verdict == "refused-by-effector"
    assert drv.current_url() == "https://app.test/"


def test_a_redirect_within_the_allowlist_is_not_refused_by_the_bound():
    """The bound does not refuse a same-origin redirect; the navigate's own check
    still reads the landed URL as not the one asked for, so it is not verified."""
    drv = RedirectingDriver({"https://app.test/old": "https://app.test/new"},
                            pages={"https://app.test/": {"title": "Home", "fields": {}}}, start="https://app.test/")
    eff = BrowserEffector(drv, allowed_origins=["https://app.test"])
    out = AccountableSurface().actuate(eff, target="https://app.test/old",
                                       content=BrowserAction("navigate", url="https://app.test/old"),
                                       authorization=_grant(["browser.navigate"]))
    assert out.acted is True and out.verdict == "failed" and out.rolled_back is True
