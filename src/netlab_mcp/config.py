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
    """Free platforms plus any EULA platforms the user has explicitly accepted."""
    allowed = set(FREE_PLATFORMS)
    for plat, env in EULA_PLATFORMS.items():
        if _truthy(os.environ.get(env)):
            allowed.add(plat)
    return allowed


def check_platforms(platforms: list[str]) -> tuple[bool, list[str], str]:
    """Return (ok, rejected, reason). Empty input is treated as ok."""
    allowed = allowed_platforms()
    rejected = sorted({p for p in platforms if p not in allowed})
    if not rejected:
        return True, [], ""
    locked = sorted(EULA_PLATFORMS)
    reason = (
        f"Platforms not permitted in this MVP: {', '.join(rejected)}. "
        f"Allowed (free containerlab images): {', '.join(sorted(allowed))}. "
        f"EULA-gated (set env to enable): {', '.join(locked)}. "
        "Licensed NOSes (nxos/iosxr/sros/junos/...) are deferred to a future "
        "self-hosted runner with image entitlements."
    )
    return False, rejected, reason
