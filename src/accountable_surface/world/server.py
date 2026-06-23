"""Zero-dep live server for the Shared World — the body operating, watched together over SSE.

stdlib http.server only. Holds ONE shared world (a WorldSession bound to a sandbox root + an
operator grant) and a set of live subscribers: a proposed action POSTed to /act runs the real
loop and is pushed to every open /world/stream connection, so the operator sees the body act in
real time. Grants are operator-supplied at startup (env or arg); the built-in fallback is an
explicit, sandbox-scoped demo grant — default-deny still holds (no grant -> nothing acts).
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from coherence_membrane.pngview import is_png

from .session import WorldSession
from .sight import sight_of, describe_sight
from .pilot import autopilot, ClaudePilot, OllamaPilot, SightfulPilot

_WEB = Path(__file__).resolve().parents[3] / "web"
_CT = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
       ".json": "application/json", ".svg": "image/svg+xml"}


def _sandbox_grant(actions=("fs.write",)) -> dict:
    """An explicit, sandbox-scoped demo grant — the person starting the server is the operator."""
    return {"authorization_version": "0.1", "receipt_id": "rcpt-world-sandbox",
            "kind": "authorization-grant", "principal": {"id": "operator", "role": "operator"},
            "agent": {"id": "world-agent"}, "intent": "operate in the local sandbox world",
            "scope": {"allowed_actions": list(actions), "allowed_targets": [],
                      "allowed_perceptions": []},
            "granted_at": "2026-06-19T00:00:00+00:00", "expires_at": "2030-01-01T00:00:00+00:00",
            "revoked": False}


def _offline_reply(snap) -> str:
    """An honest reading of the shared sight when no model is configured — never a fabrication."""
    sights = snap.get("sights") or []
    if sights:
        return "Looking with you — I can make out " + describe_sight(sights[0]) + ". What stands out to you?"
    return "Nothing is in view yet — add an image and we'll look at it together."


def _safe_name(name) -> str:
    """A safe stem for an uploaded file — alnum/._- only, no path traversal."""
    base = re.sub(r"[^A-Za-z0-9._-]", "_", str(name or "image")).strip("._") or "image"
    return base[:-4] if base.lower().endswith(".png") else base


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
        self._chat: list = []   # the small conversation memory: what they said about what they see

    @property
    def goal(self) -> str:
        with self._lock:
            return self._goal

    @property
    def chat_history(self) -> list:
        with self._lock:
            return list(self._chat)   # a copy — never hand out the live list

    def status(self) -> dict:
        """The pilot/run status, read atomically — folded into GET /world alongside the snapshot."""
        with self._lock:
            return {"pilot": self.pilot_kind, "running": self._running, "goal": self._goal}

    def chat(self, message) -> dict:
        """One turn of the conversation about what they both see — grounded in the witnessed sight,
        remembered. The pilot converses if it can; otherwise an honest reading of the sight."""
        snap = self.snapshot()                       # locks internally; take it before our own lock
        with self._lock:
            prior = list(self._chat)
            self._chat.append({"role": "user", "text": message})
        if hasattr(self.pilot, "converse"):          # the model call is OUTSIDE the lock (network)
            reply = self.pilot.converse(snap, prior, message)
        else:
            reply = _offline_reply(snap)
        with self._lock:
            self._chat.append({"role": "assistant", "text": reply})
            del self._chat[:-40]   # bounded memory — the recent conversation
            history = list(self._chat)
        return {"reply": reply, "history": history}   # return the copy, never the live list

    def act(self, **kw) -> dict:
        with self._lock:
            step = self.session.act(**kw).to_dict()
            snap = self.session.snapshot()
            subs = list(self._subs)
        for q in subs:                               # push AFTER releasing the lock (q.put can block)
            q.put(("step", step)); q.put(("world", snap))
        return step

    def snapshot(self) -> dict:
        with self._lock:
            return self.session.snapshot()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def run_autopilot(self, goal, max_steps=6) -> None:
        """Let the pilot drive the body, streaming each witnessed step. Bounded + stoppable."""
        with self._lock:                             # atomic check-and-set: no two autopilots race
            if self.pilot is None or self._running:
                return
            self._running = True
            self._goal = goal
            subs = list(self._subs)
        for q in subs:                               # status pushed OUTSIDE the lock (q.put)
            q.put(("status", {"goal": goal, "running": True, "pilot": self.pilot_kind}))
        try:
            autopilot(self, self.pilot, goal=goal, max_steps=max_steps,
                      should_continue=lambda: self.running)   # .running reads under the lock itself
        finally:
            with self._lock:
                self._running = False
                subs = list(self._subs)
            for q in subs:                           # finished signal pushed OUTSIDE the lock
                q.put(("autopilot", {"running": False}))

    def stop_autopilot(self) -> None:
        with self._lock:
            self._running = False

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
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
            snap.update(_WORLD.status())   # pilot/running/goal read atomically, folded into the snap
            return self._send(200, snap)
        if path == "/world/stream":
            return self._stream()
        if path == "/reel":
            return self._send(200, _WORLD.session.reel or {"count": 0, "fps": 0, "frames": []})
        if path == "/chat":
            return self._send(200, {"history": _WORLD.chat_history})
        if path == "/watch":
            return self._static("watch.html")
        if path == "/together":
            return self._static("together.html")
        return self._static("index.html" if path == "/" else path.lstrip("/"))

    def do_POST(self):
        path = self.path.split("?")[0]
        n = min(int(self.headers.get("Content-Length") or 0), 32 * 1024 * 1024)  # cap the body (32 MiB)
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
            try:
                steps = max(1, min(int(body.get("max_steps", 6) or 6), 24))  # bound the run
            except (ValueError, TypeError):
                return self._send(400, {"error": "max_steps must be an integer"})
            goal = str(body.get("goal", ""))
            threading.Thread(target=_WORLD.run_autopilot, args=(goal, steps), daemon=True).start()
            return self._send(200, {"started": True, "pilot": _WORLD.pilot_kind, "running": True})
        if path == "/autopilot/stop":
            _WORLD.stop_autopilot()
            return self._send(200, {"running": False})
        if path == "/upload":
            name = _safe_name(body.get("name", "image")) + ".png"
            try:
                data = base64.b64decode(body.get("png_b64", ""), validate=True)
            except Exception:
                return self._send(400, {"error": "bad image data"})
            if not is_png(data):
                return self._send(400, {"error": "not a PNG image"})
            fp = _WORLD.session.root / name
            fp.write_bytes(data)        # the operator places their own media in their sandbox world
            return self._send(200, {"ok": True, "name": name, "sight": sight_of(fp, cols=96)})
        if path == "/chat":
            message = str(body.get("message", "")).strip()[:4000]   # bound the message length
            if not message:
                return self._send(400, {"error": "empty message"})
            return self._send(200, _WORLD.chat(message))
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


def _ollama_models(host):
    """The local Ollama models, or None if Ollama isn't reachable. Stdlib only, short timeout."""
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=2) as r:
            return [m.get("name") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return None


def _build_pilot():
    """Pick the best available mind: a cloud key, else a local Ollama model, else the offline
    sight-reacting demo. Every choice is bounded by the same gate + verify + witness."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return ClaudePilot(key, model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")), "claude"
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    models = _ollama_models(host)
    if models:
        model = os.environ.get("OLLAMA_MODEL") or models[0] or "llama3.2"
        return OllamaPilot(model, host=host), f"ollama:{model}"
    return SightfulPilot(), "sightful-demo"


def serve(host=None, port=8808, root=None, grant=None):
    global _WORLD
    host = host or os.environ.get("ACCOUNTABLE_WORLD_HOST", "127.0.0.1")  # 0.0.0.0 to host on a droplet
    root = root or os.environ.get("ACCOUNTABLE_WORLD_ROOT") or (Path.cwd() / "world-sandbox")
    grant = grant or _load_grant() or _sandbox_grant()
    pilot, kind = _build_pilot()
    _WORLD = World(root, grant, pilot, kind)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"!! WARNING: binding {host} exposes this surface PUBLICLY with NO authentication — "
              "anyone who can reach this port can drive the body and read the sandbox. "
              "Only do this behind your own auth/firewall.")
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
