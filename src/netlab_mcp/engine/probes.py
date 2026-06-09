"""Capability probes for the lab path: is there a working docker + containerlab?"""
from __future__ import annotations

import shutil
import subprocess


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
