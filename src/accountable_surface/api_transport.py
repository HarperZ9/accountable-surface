"""The stdlib transport behind `ApiEffector`. Kept apart from the effector on purpose.

Zero dependencies: `urllib.request` and nothing else, matching the rest of this
repository's native posture. It carries no policy. Every bound that matters (the
service allowlist, the path shape, the gate allow, the credential door) is enforced
in `ApiEffector` before a request reaches here, so this file is a socket and not a
gate.

Honest null: this driver has no test coverage. Exercising it needs a network and a
real credential, and the suite has neither by design, so `FakeApiDriver` is what the
tests drive. Treat a first real call as unproven and watch it.
"""

from __future__ import annotations

import urllib.error
import urllib.request


class UrllibApiDriver:
    """Sends one request and returns `{"status", "body"}`. Raises nothing on a 4xx or
    5xx: an error status is a fact the effector's verify has to see, not an exception
    that hides what the service said."""

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    def request(self, method: str, url: str, headers: dict, body: bytes | None) -> dict:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return {"status": response.status, "body": response.read()}
        except urllib.error.HTTPError as exc:
            return {"status": exc.code, "body": exc.read()}
