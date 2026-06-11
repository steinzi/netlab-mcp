"""Environment + policy: where netlab lives, where we write state, which platforms are allowed."""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

# --- platform allow-list -------------------------------------------------------
# MVP: only NOSes that run as free containerlab images. Licensed NOSes
# (nxos/iosxr/sros/junos/vmx/vsrx/...) are intentionally rejected until a
# self-hosted runner with image entitlements exists (see plan, phase P5).
FREE_PLATFORMS: frozenset[str] = frozenset({"srlinux", "frr", "cumulus", "vyos", "linux"})

# Platforms allowed only when the user explicitly accepts the vendor EULA via env.
EULA_PLATFORMS: dict[str, str] = {"ceos": "NETLAB_MCP_ACCEPT_CEOS_EULA"}

# --- paths ---------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
STORE_DIR = Path(os.environ.get("NETLAB_MCP_STORE", REPO_ROOT / "store"))
ARTIFACTS_DIR = STORE_DIR / "artifacts"
WORK_BASE = Path(os.environ.get("NETLAB_MCP_WORKDIR", REPO_ROOT / ".work"))
NETLAB_EXAMPLES = REPO_ROOT / "netlab" / "tests" / "integration"


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def netlab_bin() -> str:
    """Locate the netlab executable. Prefer the same venv as this interpreter."""
    env = os.environ.get("NETLAB_MCP_NETLAB_BIN")
    if env:
        return env
    candidate = Path(sys.executable).parent / "netlab"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("netlab")
    if found:
        return found
    raise RuntimeError(
        "netlab executable not found. Install 'networklab' in this environment "
        "or set NETLAB_MCP_NETLAB_BIN."
    )


def allowed_platforms() -> set[str]:
    """Free platforms, plus operator-granted extras.

    Three opt-in ways to widen the gate beyond the free set, all explicit operator
    decisions (the operator owns the images and their licenses, not the MCP caller):
    - per-platform EULA envs (EULA_PLATFORMS),
    - NETLAB_MCP_PLATFORMS: comma-separated extra device names,
    - NETLAB_MCP_ALLOW_INSTALLED=1: any device backed by an image already loaded in
      the local docker store (it cannot pull anything new, only use what's there).
    """
    allowed = set(FREE_PLATFORMS)
    for plat, env in EULA_PLATFORMS.items():
        if _truthy(os.environ.get(env)):
            allowed.add(plat)
    extra = os.environ.get("NETLAB_MCP_PLATFORMS", "")
    allowed |= {p.strip() for p in extra.split(",") if p.strip()}
    if _truthy(os.environ.get("NETLAB_MCP_ALLOW_INSTALLED")):
        from .engine.images import devices_with_images  # lazy: avoids import cycle

        allowed |= devices_with_images()
    return allowed


def check_platforms(platforms: list[str]) -> tuple[bool, list[str], str]:
    """Return (ok, rejected, reason). Empty input is treated as ok."""
    allowed = allowed_platforms()
    rejected = sorted({p for p in platforms if p not in allowed})
    if not rejected:
        return True, [], ""
    locked = sorted(EULA_PLATFORMS)
    reason = (
        f"Platforms not permitted here: {', '.join(rejected)}. "
        f"Allowed: {', '.join(sorted(allowed))}. "
        f"EULA-gated (set env to enable): {', '.join(locked)}. "
        "Operators can widen the gate with NETLAB_MCP_PLATFORMS=<csv> or "
        "NETLAB_MCP_ALLOW_INSTALLED=1 (any device with a locally loaded image)."
    )
    return False, rejected, reason
