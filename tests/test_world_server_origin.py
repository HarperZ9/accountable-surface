"""The shared-world server answers only its own page (PARITY defect 4).

It used to send `Access-Control-Allow-Origin: *` on every route and accept a
POST to /act from any page, so any website the operator had open could drive
the body. Now no route sends a wildcard origin, and every mutating route needs
the per-session token the server writes into the pages it serves itself. A
cross-origin page can neither read that token nor send the custom header
without a preflight the server does not grant.
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from accountable_surface.world import server as ws

MUTATING = ["/act", "/autopilot", "/autopilot/stop", "/upload", "/chat", "/capture/start", "/capture/stop"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = ws.World(tmp_path / "w", ws._sandbox_grant())
    monkeypatch.setattr(ws, "_WORLD", w)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ws.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield w, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=data, headers=headers or {})
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, payload


def test_no_wildcard_cors_header(world):
    _, port = world
    for method, path in [("GET", "/world"), ("GET", "/"), ("OPTIONS", "/act"), ("POST", "/act")]:
        _, headers, _ = _call(port, method, path, {} if method == "POST" else None)
        assert "access-control-allow-origin" not in headers, (method, path)


def test_mutating_route_without_the_session_token_refuses(world):
    w, port = world
    act = {"kind": "fs.write", "target": "x.txt", "content": "hi"}
    for path in MUTATING:
        status, _, _ = _call(port, "POST", path, act, {"Content-Type": "text/plain"})
        assert status == 403, path
        status, _, _ = _call(port, "POST", path, act, {"X-World-Token": "guess"})
        assert status == 403, path
    assert not (w.session.root / "x.txt").exists()


def test_the_session_token_admits_the_page_the_server_served(world):
    w, port = world
    status, _, html = _call(port, "GET", "/")
    assert status == 200 and f'content="{w.token}"'.encode() in html
    status, _, body = _call(port, "POST", "/act", {"kind": "fs.write", "target": "x.txt", "content": "hi"},
                            {"X-World-Token": w.token})
    assert status == 200 and json.loads(body)["acted"] is True
    assert (w.session.root / "x.txt").read_text() == "hi"


def test_every_world_gets_its_own_token(tmp_path):
    a = ws.World(tmp_path / "a", ws._sandbox_grant())
    b = ws.World(tmp_path / "b", ws._sandbox_grant())
    assert a.token != b.token and len(a.token) >= 32
