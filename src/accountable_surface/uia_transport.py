"""The PowerShell transport behind the UIA rungs. Kept apart from the effector.

`uia.ps1` is run as an argv list with no shell, so nothing in a control's label can
be read as a command. The script speaks JSON on stdout and exits 0 whatever happened,
so a refusal arrives as data; anything that is not an object with `ok` is turned into
one here rather than raised, because the rungs above read answers and not exceptions.

Structural verbs only. `uia.ps1` also speaks `input` and `type`, which send keystrokes
to whatever window is in FRONT of the operator. Those are blind: they name no control,
they cannot be resolved, and nothing about them can be verified by re-reading a tree.
This driver refuses them by name, so the ladder cannot reach them by asking politely.

Honest null: the subprocess path has no test coverage. Exercising it needs Windows, a
live window, and a running application, and the suite has none of those by design, so
`FakeUiaDriver` is what the tests drive. The verb refusal above IS covered, because it
happens before anything is spawned. Treat a first real call as unproven and watch it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

STRUCTURAL_VERBS = ("windows", "tree", "value", "invoke", "setvalue", "focus")

BLIND_VERBS = {
    "input": "it sends keys to whatever window is in front, naming no control",
    "type": "it types into whatever window is in front, naming no control",
}


class PowerShellUiaDriver:
    """Runs one `uia.ps1` verb and returns its parsed answer."""

    def __init__(self, script_path: str | Path, *, executable: str = "powershell",
                 timeout: float = 30.0) -> None:
        self._script = Path(script_path).resolve()
        self._executable = executable
        self._timeout = timeout

    def run(self, verb: str, args: list) -> dict:
        if verb in BLIND_VERBS:
            return {"ok": False, "error": f"verb {verb!r} is refused: {BLIND_VERBS[verb]}"}
        if verb not in STRUCTURAL_VERBS:
            return {"ok": False, "error": f"verb {verb!r} is not one this driver runs: "
                                          f"{list(STRUCTURAL_VERBS)}"}
        argv = [self._executable, "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(self._script), verb, *[str(a) for a in args]]
        try:
            done = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=self._timeout, shell=False, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__} running uia.ps1: {exc}"}
        return _parse(done.stdout, done.stderr)


def _parse(stdout: str, stderr: str) -> dict:
    try:
        answer = json.loads(stdout or "")
    except ValueError:
        return {"ok": False, "error": f"uia.ps1 did not answer JSON: {(stderr or stdout)[:200]}"}
    if not isinstance(answer, dict) or "ok" not in answer:
        return {"ok": False, "error": "uia.ps1 answered without an 'ok' field"}
    return answer
