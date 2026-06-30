"""OS actuation for the efferent arm -- run bounded, allowlisted commands.

Inert until authorized; bounded to an allowlist + a cwd. This is the prime
IRREVERSIBLE effector: a command's effects can't be rolled back, so
`AccountableSurface.actuate` escalates to needs-human unless the operator grant
explicitly carries `allow_irreversible`. Native: a `runner` abstraction
(`SubprocessRunner` real; a fake for tests) so the accountability logic is testable
offline without spawning processes. No shell -- argv only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from coherence_membrane.observation import Observation, Provenance, Status, sha256_hex

from accountable_surface.effector import Plan, RefusedActuation, Verdict


class SubprocessRunner:
    """Real runner -- `subprocess.run`, bounded cwd, captured output, no shell."""

    def run(self, argv: list[str], cwd: str) -> dict:
        proc = subprocess.run(  # noqa: S603 (argv only, no shell; caller allowlists argv[0])
            argv, cwd=cwd, capture_output=True, text=True, timeout=30, shell=False
        )
        return {"exit_code": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:]}


class CommandEffector:
    """Runs ONLY allowlisted command names, in a bounded cwd, only on a gate allow for
    the exact plan. Commands are irreversible by construction (`reversible=False`)."""

    name = "command-effector"
    action_kind = "os.run"

    def __init__(self, runner: Any, allowed_commands, cwd: str | Path) -> None:
        self._runner = runner
        self._allowed = set(allowed_commands)
        self._cwd = Path(cwd).resolve()
        self._last: dict = {}

    def perceive(self, target: str = "") -> Observation:
        payload = f"{self._cwd}|{target}|{self._last.get('exit_code')}".encode("utf-8")
        return Observation(
            organ=self.name,
            subject=f"os://{self._cwd}",
            summary=f"cwd {self._cwd} (last exit: {self._last.get('exit_code')})",
            status=Status.PASS,
            provenance=Provenance.witness_bytes(f"os://{self._cwd}", payload, "high"),
            data={"cwd": str(self._cwd), "last_exit": self._last.get("exit_code"),
                  "stdout": self._last.get("stdout")},
        )

    def preview(self, target: str, command: list[str], before: Observation | None = None) -> Plan:
        content_sha = sha256_hex(" ".join(command).encode("utf-8"))
        digest = "sha256:" + sha256_hex(f"{self.action_kind}|{target}|{content_sha}".encode("utf-8"))
        # reversible=False -- a command's effects cannot be undone.
        return Plan(self.action_kind, target, content_sha, False, False, digest)

    def act(self, plan: Plan, allow_receipt: Any, command: list[str]) -> Observation:
        if getattr(allow_receipt, "decision", None) != "allow":
            raise RefusedActuation("no gate allow -- the effector will not run anything")
        request = getattr(allow_receipt, "request", {}) or {}
        planned = request.get("planned_action", {}) if isinstance(request, dict) else {}
        if planned.get("action_kind") != plan.action_kind or planned.get("target") != plan.target:
            raise RefusedActuation("allow receipt does not match the plan's action/target")
        if not command or command[0] not in self._allowed:
            raise RefusedActuation(f"command {command[:1]} not in the allowlist {sorted(self._allowed)}")
        if sha256_hex(" ".join(command).encode("utf-8")) != plan.content_sha256:
            raise RefusedActuation("command does not match the previewed (authorized) plan")
        self._last = self._runner.run(list(command), str(self._cwd))
        return self.perceive(plan.target)

    def verify(self, plan: Plan, after: Observation) -> Verdict:
        code = after.data.get("last_exit")
        return Verdict("pass" if code == 0 else "failed", f"command exit code: {code}")

    def rollback(self, plan: Plan) -> Observation:
        raise RefusedActuation("os.run is irreversible by construction -- nothing to roll back")

    def selftest(self) -> bool:
        """Falsifiable: an act without a gate allow must raise and run nothing."""
        ran: list = []

        class _Probe:
            def run(self, argv, cwd):
                ran.append(argv)
                return {"exit_code": 0}

        eff = CommandEffector(_Probe(), {"echo"}, ".")
        plan = eff.preview("probe", ["echo", "hi"])
        try:
            eff.act(plan, allow_receipt=None, command=["echo", "hi"])
            return False
        except RefusedActuation:
            return not ran
