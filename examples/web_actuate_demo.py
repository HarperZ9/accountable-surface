"""Native web actuation -- runnable transcript against a REAL localhost server.

No browser, no Playwright, no external deps: HttpDriver GETs + parses the page
(stdlib, via the witnessed clean fetch), WebEffector navigates + fills by accessible
label, the surface verifies by re-perceiving. Nothing acts without an operator grant.

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/web_actuate_demo.py
"""

from __future__ import annotations

import http.server
import socketserver
import threading

from accountable_surface.http_driver import HttpDriver
from accountable_surface.surface import AccountableSurface
from accountable_surface.web_effector import WebAction, WebEffector

HOME = b"<!doctype html><html><head><title>Frontier</title></head><body><a href='/signup'>signup</a></body></html>"
SIGNUP = (
    b"<!doctype html><html><head><title>Sign up</title></head><body>"
    b"<form><label for='em'>Email</label><input id='em' value=''></form></body></html>"
)


def _grant(actions):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-webdemo",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "webdemo"},
        "intent": "navigate + fill the signup form",
        "scope": {"allowed_actions": list(actions), "allowed_targets": []},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _serve():
    pages = {"/": HOME, "/signup": SIGNUP}

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
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def main() -> None:
    srv, base = _serve()
    try:
        drv = HttpDriver()
        drv.navigate(base + "/")
        eff = WebEffector(drv, allowed_origins=[base])
        surface = AccountableSurface()

        print(f"== native web actuation against {base} (no browser, stdlib only) ==\n")

        print("== PERCEIVE home (witnessed structure, not a screenshot) ==")
        home = eff.perceive()
        print(f"  url: {home.data['url']}   title: {home.data['title']!r}   digest: {home.provenance.digest[:23]}...\n")

        print("== NAVIGATE -> /signup  (authorized) ==")
        out = surface.actuate(eff, target=base + "/", content=WebAction("navigate", url=base + "/signup"),
                              authorization=_grant(["web.navigate"]))
        print(f"  acted: {out.acted}  verified: {out.verified}  now at: {drv.current_url()}\n")

        print("== perceive the form natively (fields by accessible label) ==")
        print(f"  fields: {list(eff.perceive().data['fields'])}\n")

        print("== FILL 'Email' by label  (authorized) ==")
        out = surface.actuate(eff, target=base + "/signup",
                              content=WebAction("fill", url=base + "/signup", selector="Email", value="neo@frontier.io"),
                              authorization=_grant(["web.fill"]))
        print(f"  acted: {out.acted}  verified: {out.verified}  Email now: {drv.field_value('Email')!r}\n")

        print("== FILL without a grant for it  (default-deny) ==")
        out = surface.actuate(eff, target=base + "/signup",
                              content=WebAction("fill", url=base + "/signup", selector="Email", value="x"),
                              authorization=_grant(["web.navigate"]))
        print(f"  acted: {out.acted}  decision: {out.decision}\n")

        print("== JOURNAL (every actuation, witnessed) ==")
        for entry in surface.journal:
            if entry.kind == "actuation":
                print(f"  [{entry.kind}] {entry.summary}")
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    main()
