"""Accountable Surface -- runnable transcript (the demo IS the argument).

Spins a localhost page, perceives it through the witnessed web organ, then shows
proof-surface ALLOWING an authorized action and REFUSING an unauthorized one --
every step recorded in the journal. No internet; nothing is executed.

Run: PYTHONPATH="<coherence-membrane>/src;<proof-surface>/src" python examples/demo.py
"""

from __future__ import annotations

import http.server
import socketserver
import threading

from accountable_surface.surface import AccountableSurface

PAGE = (
    b"<!doctype html><html><head><title>Frontier News</title>"
    b'<meta name="description" content="today on the frontier"></head>'
    b"<body><h1>Headline</h1><p>A model perceived this page natively.</p>"
    b'<a href="https://example.com/story">story</a></body></html>'
)


def _grant(actions, targets=()):
    return {
        "authorization_version": "0.1",
        "receipt_id": "rcpt-demo-1",
        "kind": "authorization-grant",
        "principal": {"id": "operator-1", "role": "operator"},
        "agent": {"id": "demo-agent"},
        "intent": "read and summarize the page",
        "scope": {"allowed_actions": list(actions), "allowed_targets": list(targets)},
        "granted_at": "2026-06-19T00:00:00+00:00",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "revoked": False,
    }


def _serve_once():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.handle_request, daemon=True).start()
    return srv, port


def main() -> None:
    surface = AccountableSurface()
    srv, port = _serve_once()
    url = f"http://127.0.0.1:{port}/"

    print("== PERCEIVE (native, witnessed) ==")
    obs = surface.perceive(url)
    srv.server_close()
    print(f"  title:  {obs.data.get('title')!r}")
    print(f"  links:  {obs.data.get('link_count')}    text chars: {obs.data.get('text_len')}")
    print(f"  digest: {obs.provenance.digest}")
    print(f"  status: {obs.status.value}  (a witnessed structural reading, not a screenshot)")
    print()

    grant = _grant(["summarize"])

    print("== ACT: summarize  (authorized by the grant) ==")
    allowed = surface.propose(
        action_kind="summarize",
        target=url,
        authorization=grant,
        observation=obs,
        expected_digest=obs.data["identity_sha256"],
    )
    print(f"  gate decision: {allowed.decision.upper()}")
    print(f"  checks: {allowed.checks}")
    for reason in allowed.reasons:
        print(f"    - {reason}")
    print(f"  executed by the surface: {allowed.executed}  (operator/runtime enforces an allow)")
    print()

    print("== ACT: delete  (NOT in the grant) ==")
    refused = surface.propose(action_kind="delete", target=url, authorization=grant)
    print(f"  gate decision: {refused.decision.upper()}")
    print(f"  checks: {refused.checks}")
    for reason in refused.reasons:
        print(f"    - {reason}")
    print(f"  executed by the surface: {refused.executed}  (refused by the GATE, not by a prompt)")
    print()

    print("== JOURNAL (every perception + decision, recorded) ==")
    for entry in surface.journal:
        print(f"  [{entry.kind}] {entry.summary}")


if __name__ == "__main__":
    main()
