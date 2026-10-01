"""The world server's HTTP door: loopback only, a per-run token, its own Origin only.

Before this door existed every response carried `Access-Control-Allow-Origin: *` and no
request was authenticated, so any web page the operator visited could drive /act,
/autopilot and /upload on 127.0.0.1:8808. These tests run the real handler on an
ephemeral loopback port and speak raw HTTP to it, the way a hostile page or a
DNS-rebinding attacker would.
"""
from __future__ import annotations

import http.client
import json
import threading

import pytest

from accountable_surface.world import server as srv
from accountable_surface.world.server import World, _sandbox_grant


@pytest.fixture
def door(tmp_path):
    world = World(tmp_path / "w", _sandbox_grant())
    httpd = srv.make_server(world, host="127.0.0.1", port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    port = httpd.server_address[1]
    yield {"httpd": httpd, "port": port, "token": httpd.world_token,
           "root": tmp_path / "w", "own": f"http://127.0.0.1:{port}"}
    httpd.shutdown()
    httpd.server_close()


def _req(door, method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", door["port"], timeout=5)
    hdrs = {"Host": host or f"127.0.0.1:{door['port']}"}
    hdrs.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    c.request(method, path, body=data, headers=hdrs)
    r = c.getresponse()
    streaming = path.split("?")[0] == "/world/stream" and r.status == 200
    payload = r.fp.readline() if streaming else r.read()
    c.close()
    return r, payload


def _act(door, headers, name="x.txt"):
    return _req(door, "POST", "/act", {"target": name, "content": "hi"}, headers)


def _auth(door, **extra):
    h = {"X-World-Token": door["token"], "Content-Type": "application/json"}
    h.update(extra)
    return h


def test_no_response_carries_a_wildcard_cors_header(door):
    for method, path, hdrs in (("GET", "/", {}), ("GET", "/world", _auth(door)),
                               ("OPTIONS", "/act", {"Origin": "http://evil.example"}),
                               ("POST", "/act", {"Origin": "http://evil.example"})):
        r, _ = _req(door, method, path, {} if method == "POST" else None, hdrs)
        assert r.getheader("Access-Control-Allow-Origin") is None, (method, path)
        assert r.getheader("Access-Control-Allow-Headers") is None, (method, path)


def test_act_without_the_token_is_refused_and_writes_nothing(door):
    r, _ = _act(door, {"Content-Type": "application/json"})
    assert r.status == 401
    assert not (door["root"] / "x.txt").exists()


def test_act_with_a_wrong_token_is_refused(door):
    r, _ = _act(door, {"Content-Type": "application/json", "X-World-Token": "nope"})
    assert r.status == 401
    assert not (door["root"] / "x.txt").exists()


def test_cross_site_simple_post_is_refused_even_with_a_stolen_token(door):
    """A text/plain POST skips the browser's preflight; the Origin check still stops it."""
    r, _ = _act(door, _auth(door, Origin="http://evil.example", **{"Content-Type": "text/plain"}))
    assert r.status == 403
    assert not (door["root"] / "x.txt").exists()


def test_foreign_origin_is_refused_with_the_token(door):
    r, _ = _act(door, _auth(door, Origin="http://evil.example"))
    assert r.status == 403
    r, _ = _act(door, _auth(door, Origin="null"))
    assert r.status == 403
    assert not (door["root"] / "x.txt").exists()


def test_dns_rebinding_host_is_refused(door):
    """A rebinding page is same-origin with the attacker's name; its Host header gives it away."""
    r, _ = _req(door, "POST", "/act", {"target": "x.txt", "content": "hi"},
                _auth(door, Origin=f"http://evil.example:{door['port']}"),
                host=f"evil.example:{door['port']}")
    assert r.status == 403
    r, _ = _req(door, "GET", "/", host=f"evil.example:{door['port']}")
    assert r.status == 403
    assert not (door["root"] / "x.txt").exists()


def test_non_json_post_is_refused(door):
    r, _ = _act(door, _auth(door, **{"Content-Type": "text/plain"}))
    assert r.status == 415


def test_own_origin_with_token_acts(door):
    r, payload = _act(door, _auth(door, Origin=door["own"]))
    assert r.status == 200, payload
    assert json.loads(payload)["acted"] is True
    assert (door["root"] / "x.txt").read_text() == "hi"


def test_headerless_local_client_with_token_acts(door):
    r, _ = _act(door, _auth(door), name="cli.txt")
    assert r.status == 200
    assert (door["root"] / "cli.txt").exists()


@pytest.mark.parametrize("path", ["/world", "/reel", "/chat", "/world/stream"])
def test_reads_need_the_token(door, path):
    r, _ = _req(door, "GET", path)
    assert r.status == 401


def test_reads_with_the_token_answer(door):
    r, payload = _req(door, "GET", "/world", headers={"X-World-Token": door["token"]})
    assert r.status == 200 and "files" in json.loads(payload)


def test_event_stream_takes_the_token_as_a_query_param(door):
    """EventSource cannot set headers, so the stream alone accepts ?token=."""
    r, first = _req(door, "GET", "/world/stream?token=" + door["token"])
    assert r.status == 200
    assert first.startswith(b"event: world")
    r, _ = _req(door, "GET", "/world?token=" + door["token"])
    assert r.status == 401   # only the stream takes the query form


@pytest.mark.parametrize("path", ["/autopilot", "/upload", "/chat", "/capture/start",
                                  "/autopilot/stop", "/capture/stop"])
def test_every_post_route_needs_the_token(door, path):
    r, _ = _req(door, "POST", path, {}, {"Content-Type": "application/json"})
    assert r.status == 401


def test_static_pages_load_without_the_token_and_do_not_leak_it(door):
    r, payload = _req(door, "GET", "/")
    assert r.status == 200
    assert door["token"].encode() not in payload


def test_options_preflight_grants_nothing(door):
    r, _ = _req(door, "OPTIONS", "/act", headers={"Origin": "http://evil.example",
                                                  "Access-Control-Request-Method": "POST"})
    assert r.status == 403
    assert r.getheader("Access-Control-Allow-Methods") is None


def test_tokens_are_fresh_per_run_and_long(tmp_path):
    w = World(tmp_path / "w", _sandbox_grant())
    a = srv.make_server(w, host="127.0.0.1", port=0)
    b = srv.make_server(w, host="127.0.0.1", port=0)
    try:
        assert a.world_token != b.world_token
        assert len(a.world_token) >= 32
    finally:
        a.server_close(); b.server_close()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])
def test_non_loopback_bind_is_refused(tmp_path, host):
    w = World(tmp_path / "w", _sandbox_grant())
    with pytest.raises(ValueError, match="loopback"):
        srv.make_server(w, host=host, port=0)


def test_negative_content_length_does_not_hang(door):
    c = http.client.HTTPConnection("127.0.0.1", door["port"], timeout=5)
    c.putrequest("POST", "/act", skip_host=True)
    c.putheader("Host", f"127.0.0.1:{door['port']}")
    c.putheader("X-World-Token", door["token"])
    c.putheader("Content-Type", "application/json")
    c.putheader("Content-Length", "-5")
    c.endheaders()
    r = c.getresponse()
    payload = r.read()
    c.close()
    assert r.status in (400, 200)
    if r.status == 200:
        assert json.loads(payload)["acted"] is False
