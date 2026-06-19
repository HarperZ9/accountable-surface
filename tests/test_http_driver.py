"""Tests for the native HTTP/HTML page driver (stdlib only, no browser).

`parse_html` is pure/deterministic; the driver tests run against a localhost
stdlib http.server (127.0.0.1, no internet). Proves WebEffector drives a *real*
server natively, end-to-end, under the accountable loop.
"""

from __future__ import annotations

import http.server
import socketserver
import threading

import pytest

from accountable_surface.http_driver import HttpDriver, parse_html
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import WebAction, WebEffector

HTML_HOME = b"<!doctype html><html><head><title>Home</title></head><body><a href='/form'>form</a></body></html>"
HTML_FORM = (
    b"<!doctype html><html><head><title>Sign up</title></head><body>"
    b"<form><label for='em'>Email</label><input id='em' name='email' value=''>"
    b"<input name='nick' value='neo'></form></body></html>"
)


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-http-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "http-agent"},
        "intent": "native http test",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


@pytest.fixture
def site():
    pages = {"/": HTML_HOME, "/form": HTML_FORM}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = pages.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_parse_html_extracts_title_and_fields():
    parsed = parse_html("http://x/form", HTML_FORM.decode())
    assert parsed["title"] == "Sign up"
    assert parsed["fields"]["Email"] == ""  # keyed by label-for
    assert "nick" in parsed["fields"]  # keyed by name attribute


def test_navigate_fetches_and_parses(site):
    drv = HttpDriver()
    drv.navigate(site + "/form")
    snap = drv.snapshot()
    assert snap["title"] == "Sign up"
    assert "Email" in snap["fields"]
    assert drv.current_url() == site + "/form"


def test_fill_stages_value_in_snapshot(site):
    drv = HttpDriver()
    drv.navigate(site + "/form")
    drv.fill("Email", "neo@matrix.io")
    assert drv.field_value("Email") == "neo@matrix.io"
    assert drv.snapshot()["fields"]["Email"] == "neo@matrix.io"


def test_back_refetches_prior_page(site):
    drv = HttpDriver()
    drv.navigate(site + "/")
    drv.navigate(site + "/form")
    drv.back()
    assert drv.current_url() == site + "/"
    assert drv.snapshot()["title"] == "Home"


def test_actuate_native_navigation_is_verified(site):
    drv = HttpDriver()
    drv.navigate(site + "/")
    eff = WebEffector(drv, allowed_origins=[site])
    surface = AccountableSurface()
    out = surface.actuate(
        eff,
        target=site + "/",
        content=WebAction("navigate", url=site + "/form"),
        authorization=_grant(["web.navigate"]),
    )
    assert out.acted is True
    assert out.verified is True
    assert drv.current_url() == site + "/form"
    assert any(e.kind == "actuation" for e in surface.journal)


@pytest.fixture
def post_site():
    thanks = b"<!doctype html><html><head><title>Thanks</title></head><body>ok</body></html>"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/form":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(HTML_FORM)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(thanks)

        def log_message(self, *args):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_http_submit_posts_and_lands_on_confirmation(post_site):
    drv = HttpDriver()
    drv.navigate(post_site + "/form")
    drv.fill("Email", "neo@x.io")
    drv.submit(post_site + "/submit", {"Email": "neo@x.io"})
    assert drv.snapshot()["title"] == "Thanks"  # the POST response, perceived
    assert drv.current_url() == post_site + "/submit"
