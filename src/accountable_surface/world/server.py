"""Zero-dep live server for the Shared World — the body operating, watched together over SSE.

stdlib http.server only. Holds ONE shared world (a WorldSession bound to a sandbox root + an
operator grant) and a set of live subscribers: a proposed action POSTed to /act runs the real
loop and is pushed to every open /world/stream connection, so the operator sees the body act in
real time. Grants are operator-supplied at startup (env or arg); the built-in fallback is an
explicit, sandbox-scoped demo grant — default-deny still holds (no grant -> nothing acts).
"""
from __future__ import annotations

import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .session import WorldSession
from .pilot import autopilot, ClaudePilot, ScriptedPilot, Proposal

_WEB = Path(__file__).resolve().parents[3] / "web"
_CT = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
       ".json": "application/json", ".svg": "image/svg+xml"}


def _sandbox_grant(actions=("fs.write",)) -> dict:
    """An explicit, sandbox-scoped demo grant — the person starting the server is the operator."""
    return {"authorization_version": "0.1", "receipt_id": "rcpt-world-sandbox",
            "kind": "authorization-grant", "principal": {"id": "operator", "role": "operator"},
            "agent": {"id": "world-agent"}, "intent": "operate in the local sandbox world",
            "scope": {"allowed_actions": list(actions), "allowed_targets": []},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00",
            "revoked": False}


class World:
    """Process-wide shared world: one WorldSession + a pilot + its live subscribers (thread-safe)."""

    def __init__(self, root, grant, pilot=None, pilot_kind="none"):
        self.session = WorldSession(root, grant)
        self.pilot = pilot
        self.pilot_kind = pilot_kind
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._running = False
        self._goal = ""

    @property
    def goal(self) -> str:
        return self._goal

    def act(self, **kw) -> dict:
        with self._lock:
            step = self.session.act(**kw).to_dict()
            snap = self.session.snapshot()
        for q in list(self._subs):
            q.put(("step", step)); q.put(("world", snap))
        return step

    def snapshot(self) -> dict:
        with self._lock:
            return self.session.snapshot()

    @property
    def running(self) -> bool:
        return self._running

    def run_autopilot(self, goal, max_steps=6) -> None:
        """Let the pilot drive the body, streaming each witnessed step. Bounded + stoppable."""
        if self.pilot is None or self._running:
            return
        self._running = True
        self._goal = goal
        for q in list(self._subs):
            q.put(("status", {"goal": goal, "running": True, "pilot": self.pilot_kind}))
        try:
            autopilot(self, self.pilot, goal=goal, max_steps=max_steps,
                      should_continue=lambda: self._running)
        finally:
            self._running = False
            for q in list(self._subs):
                q.put(("autopilot", {"running": False}))

    def stop_autopilot(self) -> None:
        self._running = False

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        self._subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass


_WORLD: World | None = None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/world":
            snap = _WORLD.snapshot()
            snap["pilot"], snap["running"], snap["goal"] = _WORLD.pilot_kind, _WORLD.running, _WORLD.goal
            return self._send(200, snap)
        if path == "/world/stream":
            return self._stream()
        if path == "/watch":
            return self._static("watch.html")
        return self._static("index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        if path == "/act":
            try:
                step = _WORLD.act(kind=body.get("kind", "fs.write"), target=body.get("target", ""),
                                  content=body.get("content", ""), justification=body.get("justification", ""))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(200, step)
        if path == "/autopilot":
            if _WORLD.pilot is None:
                return self._send(409, {"error": "no pilot configured"})
            goal, steps = str(body.get("goal", "")), int(body.get("max_steps", 6))
            threading.Thread(target=_WORLD.run_autopilot, args=(goal, steps), daemon=True).start()
            return self._send(200, {"started": True, "pilot": _WORLD.pilot_kind, "running": True})
        if path == "/autopilot/stop":
            _WORLD.stop_autopilot()
            return self._send(200, {"running": False})
        return self._send(404, {"error": "not found"})

    def _stream(self):
        q = _WORLD.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self._sse("world", _WORLD.snapshot())
            while True:
                try:
                    kind, data = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n"); self.wfile.flush(); continue
                self._sse(kind, data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            _WORLD.unsubscribe(q)

    def _sse(self, event, data):
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _static(self, rel):
        fp = (_WEB / rel).resolve()
        if not fp.is_file() or _WEB not in fp.parents:
            return self._send(404, {"error": "not found"})
        self._send(200, fp.read_bytes(), _CT.get(fp.suffix.lower(), "application/octet-stream"))

    def log_message(self, *a):
        pass  # quiet by default


def _load_grant():
    p = os.environ.get("ACCOUNTABLE_WORLD_GRANT")
    if p and Path(p).is_file():
        return json.loads(Path(p).read_text(encoding="utf-8"))
    return None


def _demo_pilot():
    """An offline stand-in for the real model — a fixed, honest two-step sequence. The real
    ClaudePilot drives the moment ANTHROPIC_API_KEY is present."""
    return ScriptedPilot([
        Proposal(target="README.md", justification="document the world",
                 reasoning="A world needs a front door — I'll write a README first.",
                 content="# The Shared World\n\nA model and an operator co-inhabit one accountable "
                         "surface.\nEvery action is gated, witnessed, and re-checkable.\n"),
        Proposal(target="NOTES.md", justification="record the operating premises",
                 reasoning="Now the premises, so the intent is on the record before going further.",
                 content="- perceive the witnessed state, not memory\n- the gate decides every "
                         "action\n- verify the work, then witness it\n"),
    ])


def _build_pilot():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return ClaudePilot(key, model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")), "claude"
    return _demo_pilot(), "scripted-demo"


def serve(host="127.0.0.1", port=8808, root=None, grant=None):
    global _WORLD
    root = root or os.environ.get("ACCOUNTABLE_WORLD_ROOT") or (Path.cwd() / "world-sandbox")
    grant = grant or _load_grant() or _sandbox_grant()
    pilot, kind = _build_pilot()
    _WORLD = World(root, grant, pilot, kind)
    httpd = ThreadingHTTPServer((host, port), Handler)
    actions = _WORLD.session.grant.get("scope", {}).get("allowed_actions", [])
    print(f"shared world on http://{host}:{port}  root={_WORLD.session.root}  "
          f"grant={actions}  pilot={kind}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    import sys
    serve(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8808)
