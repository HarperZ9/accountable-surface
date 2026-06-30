"""Goal/task mode -- runnable transcript: bounded autonomy against a real localhost form.

The surface pursues a multi-step goal (navigate -> fill) autonomously within ONE
operator grant -- no per-step prompt -- then the same goal with an UNauthorized step
HALTS at that step. Every step gated + verified + journaled. No browser, no deps.

Run: PYTHONPATH="src;<coherence-membrane>/src;<proof-surface>/src" python examples/goal_demo.py
"""

from __future__ import annotations

import http.server
import socketserver
import threading

from accountable_surface.http_driver import HttpDriver
from accountable_surface.surface import AccountableSurface, Step
from accountable_surface.web_effector import WebAction, WebEffector

HOME = b"<!doctype html><html><head><title>Frontier</title></head><body><a href='/signup'>signup</a></body></html>"
SIGNUP = (
    b"<!doctype html><html><head><title>Sign up</title></head><body>"
    b"<form><label for='em'>Email</label><input id='em' value=''></form></body></html>"
)


def _grant(actions):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-goaldemo",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "goaldemo"},
        "intent": "sign up: navigate to the form and fill the email",
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


def _signup_goal(base):
    drv = HttpDriver()
    drv.navigate(base + "/")
    eff = WebEffector(drv, allowed_origins=[base])
    steps = [
        Step(eff, base + "/", WebAction("navigate", url=base + "/signup")),
        Step(eff, base + "/signup", WebAction("fill", url=base + "/signup", selector="Email", value="neo@frontier.io")),
    ]
    return AccountableSurface(), steps, drv


def main() -> None:
    srv, base = _serve()
    try:
        print(f"== bounded autonomy against {base} (no browser, stdlib only) ==\n")

        surface, steps, drv = _signup_goal(base)
        print("== GOAL: sign up -- grant authorizes web.navigate + web.fill ==")
        out = surface.pursue("sign-up", steps, authorization=_grant(["web.navigate", "web.fill"]))
        print(f"  achieved: {out.achieved}   steps acted: {out.steps_acted}/{out.steps_attempted}")
        print(f"  Email on the page: {drv.field_value('Email')!r}   (navigate THEN fill, no per-step prompt)\n")

        surface2, steps2, drv2 = _signup_goal(base)
        print("== GOAL: sign up -- grant authorizes web.navigate ONLY (fill not allowed) ==")
        out = surface2.pursue("sign-up", steps2, authorization=_grant(["web.navigate"]))
        print(f"  achieved: {out.achieved}   steps acted: {out.steps_acted}/{out.steps_attempted}")
        print(f"  halted: {out.halted_reason}")
        print(f"  Email on the page: {drv2.field_value('Email')!r}   (the unauthorized step never ran)\n")

        print("== JOURNAL (second goal -- every step + the goal record, witnessed) ==")
        for entry in surface2.journal:
            if entry.kind in ("actuation", "goal"):
                print(f"  [{entry.kind}] {entry.summary}")
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    main()
