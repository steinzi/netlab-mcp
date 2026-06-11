"""Run the netlab CLI in an isolated working directory.

netlab is cwd/lockfile-stateful (writes clab.yml, netlab.lock, snapshot into cwd and
os.chdir's internally), so every request gets its own temp dir. Offline commands run in
fresh subprocesses against isolated dirs and are safe to run concurrently; lab commands
share the docker daemon and must be serialized via LAB_LOCK.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import WORK_BASE, netlab_bin

# Serializes everything that touches docker/containerlab/sudo.
LAB_LOCK = threading.Lock()

TIMEOUT_RC = 124


@dataclass
class RunResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def error_lines(self) -> list[str]:
        """Best-effort extraction of netlab error/warning lines for tool output.

        Includes netlab's structured error categories (IncorrectValue/Type, MissingValue,
        ...) which don't contain the word "error" but carry the actionable message.
        """
        markers = (
            "error", "fatal", "[warning]", "traceback", "errors encountered",
            "incorrectvalue", "incorrecttype", "incorrectattr", "incorrectkey",
            "missingvalue", "missingdependency", "wrongtype",
        )
        out: list[str] = []
        for stream in (self.stderr, self.stdout):
            for line in (stream or "").splitlines():
                s = line.strip()
                if not s:
                    continue
                low = s.lower()
                if any(m in low for m in markers) and s not in out:
                    out.append(s)
        if not out and not self.ok:
            tail = (self.stderr or self.stdout or "").strip().splitlines()[-5:]
            out = [t.strip() for t in tail if t.strip()]
        return out


def new_workdir(prefix: str = "nlmcp-") -> Path:
    WORK_BASE.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(WORK_BASE)))


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _terminate_group(proc: subprocess.Popen) -> None:
    """Kill the subprocess and every grandchild it spawned (ansible, containerlab, docker).

    `subprocess`'s own timeout only kills the direct child, orphaning netlab's long-running
    grandchildren — they keep spinning against a half-built lab (observed: stuck
    `netlab initial`/`ansible-playbook` after a deploy timeout). The child is started in its
    own session (`start_new_session=True`) so its pid is a process-group leader; signalling
    the negative pgid reaches the whole tree. Best-effort: root-owned (sudo containerlab)
    members may reject the signal (EPERM) — the `finally` `netlab down` is the backstop for
    those, while the toor-owned ansible/netlab grandchildren this is aimed at do die here.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            break
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def run_netlab(
    args: list[str],
    cwd: Path,
    timeout: int = 120,
    env_extra: dict[str, str] | None = None,
) -> RunResult:
    """Invoke `netlab <args>` in `cwd`, capturing output. Never raises on timeout/error."""
    cmd = [netlab_bin(), *args]
    env = os.environ.copy()
    # We parse netlab stdout (inspect JSON, version line, validate markers); ANSI color
    # codes from rich corrupt that. ANSIBLE_FORCE_COLOR covers the embedded ansible runs;
    # NO_COLOR + dropping any inherited FORCE_COLOR covers netlab's own rich output, which
    # otherwise colorizes even when piped (e.g. when FORCE_COLOR is set in the environment).
    env.setdefault("ANSIBLE_FORCE_COLOR", "false")
    env["NO_COLOR"] = "1"
    env.pop("FORCE_COLOR", None)
    if env_extra:
        env.update(env_extra)
    try:
        # start_new_session: own process group, so a timeout can kill the whole subtree
        # (netlab -> ansible/containerlab/docker), not just the direct child.
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
    except OSError as e:
        # e.g. NETLAB_MCP_NETLAB_BIN pointing at a missing/non-executable path. Keep the
        # "never raises" contract so callers (host_check above all) degrade to error
        # handling instead of crashing the tool call.
        return RunResult(cmd, 127, "", f"error: cannot execute {cmd[0]!r}: {e}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return RunResult(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        _terminate_group(proc)
        stdout, stderr = proc.communicate()
        return RunResult(cmd, TIMEOUT_RC, stdout or "",
                         (stderr or "") + f"\n[timeout after {timeout}s]")


@lru_cache(maxsize=1)
def netlab_version() -> str:
    """`netlab version` -> '26.06' (cached). Falls back to 'unknown'."""
    wd = new_workdir("nlmcp-ver-")
    try:
        r = run_netlab(["version"], cwd=wd, timeout=30)
        for line in r.stdout.splitlines():
            if "version" in line.lower():
                parts = line.split()
                if parts:
                    return parts[-1]
        return "unknown"
    finally:
        cleanup(wd)
