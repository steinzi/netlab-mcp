"""Run the netlab CLI in an isolated working directory.

netlab is cwd/lockfile-stateful (writes clab.yml, netlab.lock, snapshot into cwd and
os.chdir's internally), so every request gets its own temp dir. Offline commands run in
fresh subprocesses against isolated dirs and are safe to run concurrently; lab commands
share the docker daemon and must be serialized via LAB_LOCK.
"""
from __future__ import annotations

import os
import shutil
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


def run_netlab(
    args: list[str],
    cwd: Path,
    timeout: int = 120,
    env_extra: dict[str, str] | None = None,
) -> RunResult:
    """Invoke `netlab <args>` in `cwd`, capturing output. Never raises on timeout/error."""
    cmd = [netlab_bin(), *args]
    env = os.environ.copy()
    # Keep netlab non-interactive and deterministic.
    env.setdefault("ANSIBLE_FORCE_COLOR", "false")
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return RunResult(cmd, p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return RunResult(cmd, TIMEOUT_RC, stdout, stderr + f"\n[timeout after {timeout}s]")


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
