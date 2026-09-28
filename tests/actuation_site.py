"""A local fixture site on 127.0.0.1 for the actuation pipeline tests.

It serves the pages in tests/fixtures/pages (with {{ORIGIN}} filled in), keeps
every request it receives so a test can prove nothing reached it after a stop,
and records orders posted to /order/submit so a test can read the effect back
through a separate GET of /orders. Nothing here reaches off the machine.
"""

from __future__ import annotations

import http.server
import threading
import urllib.parse
from pathlib import Path

PAGES = Path(__file__).resolve().parent / "fixtures" / "pages"


class Site:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.orders: list[dict] = []
        self._httpd = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def url(self, path: str) -> str:
        return self.origin + path

    def start(self) -> "Site":
        site = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                site.requests.append(("GET", self.path))
                site._get(self)

            def do_POST(self):  # noqa: N802
                site.requests.append(("POST", self.path))
                length = int(self.headers.get("Content-Length") or 0)
                site._post(self, urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8")))

            def log_message(self, *args):
                pass

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def _send(self, handler, status: int, html: str, headers: dict | None = None) -> None:
        body = html.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _get(self, handler) -> None:
        path = urllib.parse.urlsplit(handler.path).path
        if path == "/orders":
            items = "".join(f"<li>Order {i + 1}: quantity {o['quantity']}</li>" for i, o in enumerate(self.orders))
            return self._send(handler, 200, f"<title>Orders</title><ul>{items}</ul>")
        if path == "/challenge-403":
            return self._send(handler, 403, "<title>Just a moment...</title>", {"cf-mitigated": "challenge"})
        if path == "/wire-all-funds":
            return self._send(handler, 200, "<title>Transfer</title><button type='button'>Confirm transfer</button>")
        page = PAGES / ((path.strip("/") or "notes") + ".html")
        if not page.is_file():
            return self._send(handler, 404, "<title>Not found</title>")
        self._send(handler, 200, page.read_text(encoding="utf-8").replace("{{ORIGIN}}", self.origin))

    def _post(self, handler, form: dict) -> None:
        if handler.path == "/order/submit":
            # HttpDriver posts fields keyed by accessible name ("Quantity"), a
            # browser posts them by name attribute ("quantity"); accept either.
            self.orders.append({"quantity": (form.get("quantity") or form.get("Quantity") or ["?"])[0]})
            return self._send(handler, 200, f"<title>Order received</title><p>Order {len(self.orders)} received</p>")
        self._send(handler, 404, "<title>Not found</title>")
