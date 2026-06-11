"""Capability probes for the lab path: is there a working docker + containerlab?"""
from __future__ import annotations

import re
import shutil
import subprocess
import time


def _cmd_ok(cmd: list[str], timeout: int = 10) -> bool:
    if shutil.which(cmd[0]) is None:
        return False
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def docker_ok() -> bool:
    return _cmd_ok(["docker", "info"])


def containerlab_ok() -> bool:
    return shutil.which("containerlab") is not None


def lab_available() -> dict:
    """Return {ok, docker, containerlab, reasons[]}. ok means validate_in_lab can run here."""
    d = docker_ok()
    c = containerlab_ok()
    reasons: list[str] = []
    if not d:
        reasons.append("docker not available (need a running Docker daemon)")
    if not c:
        reasons.append(
            "containerlab not installed (Linux host required; not available on macOS directly)"
        )
    return {"ok": d and c, "docker": d, "containerlab": c, "reasons": reasons}


_PROBE_TTL_S = 30.0
_probe_cache: tuple[float, dict] | None = None


def lab_available_cached() -> dict:
    """lab_available() behind a ~30s cache, for hot paths like a public /health route
    where each call would otherwise fork docker subprocesses."""
    global _probe_cache
    now = time.monotonic()
    if _probe_cache and now - _probe_cache[0] < _PROBE_TTL_S:
        return _probe_cache[1]
    result = lab_available()
    _probe_cache = (now, result)
    return result


def _cmd_output(cmd: list[str], timeout: int = 10) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr) if p.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None


def _first_line(text: str | None) -> str | None:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[0] if lines else None


def tool_versions() -> dict[str, str | None]:
    """Versions of the binaries the lab path shells out to. None = not found/not working."""
    clab = _cmd_output(["containerlab", "version"])
    if clab:  # containerlab prints an ASCII-art banner; dig out the version line
        m = re.search(r"version\s*:\s*(\S+)", clab, re.IGNORECASE)
        clab = m.group(1) if m else _first_line(clab)
    return {
        "docker": _first_line(_cmd_output(["docker", "--version"])),
        "containerlab": clab,
        "ansible": _first_line(_cmd_output(["ansible", "--version"])),
    }
