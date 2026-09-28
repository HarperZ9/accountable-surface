"""Same-origin guard for the shared-world server.

The server used to answer every origin (`Access-Control-Allow-Origin: *`) and
accept a POST from any page, so a website open in the operator's browser could
drive the body through a plain cross-origin POST. The guard is two parts:

- no route sends an allow-origin header, so a cross-origin page cannot read a
  response or pass the preflight a custom header needs;
- every mutating route requires `X-World-Token`, a per-session secret the server
  writes into the HTML pages it serves itself. Only a page the server served can
  read it.

The token guards the local page against other pages. It is not operator
authority: the grant still decides what an action may do.
"""

from __future__ import annotations

import hmac
import secrets

HEADER = "X-World-Token"
MUTATING = frozenset({"/act", "/autopilot", "/autopilot/stop", "/upload", "/chat",
                      "/capture/start", "/capture/stop"})


def new_token() -> str:
    return secrets.token_urlsafe(32)


def admitted(path: str, headers, token: str) -> bool:
    """Whether a POST to `path` may proceed: non-mutating paths pass, mutating
    paths need the session token, compared in constant time."""
    if path not in MUTATING:
        return True
    offered = headers.get(HEADER) or ""
    return bool(token) and hmac.compare_digest(offered.encode("utf-8"), token.encode("utf-8"))


def inject(html: bytes, token: str) -> bytes:
    """Write the token into a served page as a meta tag the page's own script reads."""
    meta = f'<meta name="world-token" content="{token}">'.encode("utf-8")
    if b"</head>" in html:
        return html.replace(b"</head>", meta + b"</head>", 1)
    return meta + html
