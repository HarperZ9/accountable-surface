"""The world server's HTTP door: loopback bind, a per-run token, and its own Origin only.

The world server drives real actuation (/act, /autopilot, /upload). A browser will send
requests to 127.0.0.1 from any page the operator visits, so the door has to tell the
operator's own page apart from everyone else's. Four checks do that, in this order:

1. **Host.** The Host header must name the loopback address the server bound. A
   DNS-rebinding page shares an origin with the attacker's hostname, so its Host header
   carries that hostname and fails here.
2. **Origin.** When a browser sends Origin (or Sec-Fetch-Site), it must be the server's
   own. A foreign page's request carries its own origin, `null` included.
3. **Token.** Every API route needs the per-run token, generated at start and printed to
   the terminal. The header is `X-World-Token`. EventSource cannot set headers, so the
   event stream alone also accepts `?token=`. Static pages carry no secret and load
   without it.
4. **Content type.** A POST must declare `application/json`. A `text/plain` POST is the
   one cross-site write a browser sends without a preflight.

No response carries an Access-Control-Allow-* header, so no other origin can read one.
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
from urllib.parse import parse_qs, urlsplit

TOKEN_HEADER = "X-World-Token"
STREAM_PATH = "/world/stream"
_API_GET = ("/world", STREAM_PATH, "/reel", "/chat")
_LOOPBACK_NAMES = ("localhost",)


def new_token() -> str:
    """A fresh per-run token: 32 random bytes, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def require_loopback(host: str) -> str:
    """Return `host` if it is a loopback address or `localhost`; raise ValueError otherwise."""
    name = str(host or "").strip().strip("[]")
    if name.lower() in _LOOPBACK_NAMES:
        return "localhost"
    try:
        if ipaddress.ip_address(name).is_loopback:
            return name
    except ValueError:
        pass
    raise ValueError(f"the world server binds loopback only; refusing host {host!r}")


def allowed_hosts(host: str, port: int) -> frozenset[str]:
    """The Host header values that name this server: its bound address and `localhost`."""
    shown = f"[{host}]" if ":" in host else host
    names = {f"{shown}:{port}", f"localhost:{port}"}
    if host == "localhost":
        names.add(f"127.0.0.1:{port}")
    return frozenset(n.lower() for n in names)


def is_api_get(path: str) -> bool:
    return path in _API_GET


def check_request(method: str, raw_path: str, headers, *, token: str, hosts) -> tuple[int, str] | None:
    """Return `(status, reason)` to refuse the request, or None to let it through."""
    host = (headers.get("Host") or "").strip().lower()
    if host not in hosts:
        return 403, "unexpected Host header"
    origin = headers.get("Origin")
    if origin is not None and origin.strip().lower() not in {f"http://{h}" for h in hosts}:
        return 403, "cross-origin request refused"
    fetch_site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if fetch_site not in ("", "same-origin", "none"):
        return 403, "cross-site request refused"
    if method == "OPTIONS":
        return 403, "no cross-origin access"
    parts = urlsplit(raw_path)
    path = parts.path
    if method == "GET" and not is_api_get(path):
        return None   # static pages hold no secret
    presented = headers.get(TOKEN_HEADER) or ""
    if not presented and method == "GET" and path == STREAM_PATH:
        presented = (parse_qs(parts.query).get("token") or [""])[0]
    if not presented or not hmac.compare_digest(presented.encode(), token.encode()):
        return 401, "missing or wrong world token"
    if method == "POST":
        ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return 415, "POST bodies must be application/json"
    return None
