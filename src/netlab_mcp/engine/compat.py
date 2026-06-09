"""Declared module/platform support, from `netlab show module-support --format yaml`.

This is what netlab *claims* a device supports — distinct from what has been *observed* to
pass in a lab. The server overlays observed verdicts (from the matrix store) on top of this.
"""
from __future__ import annotations

import yaml

from .runner import cleanup, new_workdir, run_netlab


def declared_support(
    module: str | None = None,
    platforms: list[str] | None = None,
    timeout: int = 60,
) -> dict:
    """Declared support, optionally narrowed to `platforms`.

    netlab's `-d DEVICE` filter takes a single device, so for multi-platform requests we
    fetch the full dump and filter the result dict in-process (fixes the case where a
    2+ platform filter was silently ignored).
    """
    args = ["show", "module-support", "--format", "yaml"]
    if module:
        args += ["-m", module]
    if platforms and len(platforms) == 1:
        args += ["-d", platforms[0]]
    wd = new_workdir("nlmcp-compat-")
    try:
        r = run_netlab(args, cwd=wd, timeout=timeout)
        if not r.ok:
            return {"ok": False, "error": (r.stderr or r.stdout).strip(), "data": {}}
        try:
            data = yaml.safe_load(r.stdout) or {}
        except yaml.YAMLError as e:
            return {"ok": False, "error": f"yaml parse error: {e}", "data": {}}
        if platforms:
            want = set(platforms)
            data = {k: v for k, v in data.items() if k in want}
        return {"ok": True, "data": data}
    finally:
        cleanup(wd)
