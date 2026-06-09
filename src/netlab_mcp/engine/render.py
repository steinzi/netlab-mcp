"""Offline config render: `netlab create` + `netlab initial -o <dir>` (no docker, no devices).

netlab writes one file per (node, module): `<node>.<module>.<ext>` where the extension
varies by platform (srlinux -> .cfg, frr -> .sh and .cfg). We glob `<node>.*` rather than
assuming `.cfg`.
"""
from __future__ import annotations

from pathlib import Path

from ..config import check_platforms
from ..models import DISCLAIMER
from .runner import RunResult, cleanup, new_workdir, run_netlab
from .transform import resolved_node_devices


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _parse_configs(configs_dir: Path, nodes: list[str] | None) -> dict[str, dict[str, str]]:
    """configs/<node>.<module>.<ext> -> {node: {module: text}}."""
    want = set(nodes) if nodes else None
    per_node: dict[str, dict[str, str]] = {}
    if not configs_dir.is_dir():
        return per_node
    for f in sorted(configs_dir.iterdir()):
        if not f.is_file():
            continue
        parts = f.name.split(".")
        if len(parts) < 2:
            continue
        node, module = parts[0], parts[1]
        if want is not None and node not in want:
            continue
        text = _read(f)
        if text is None:
            continue
        per_node.setdefault(node, {})[module] = text
    return per_node


def _fail(stage: str, r: RunResult, clab: str | None = None) -> dict:
    return {
        "ok": False,
        "stage": stage,
        "errors": r.error_lines(),
        "per_node": {},
        "clab_yaml": clab,
        "disclaimer": DISCLAIMER,
    }


def _policy_fail(errors: list[str], rejected: list[str] | None = None) -> dict:
    return {
        "ok": False,
        "stage": "policy",
        "errors": errors,
        "rejected": rejected or [],
        "per_node": {},
        "clab_yaml": None,
        "disclaimer": DISCLAIMER,
    }


def render_config(
    topology_yaml: str,
    nodes: list[str] | None = None,
    *,
    keep_dir: bool = False,
    timeout: int = 120,
) -> dict:
    """Render per-device config for a topology. Returns per_node config + clab.yml text.

    If keep_dir is True the workdir is left on disk and its path is returned as `workdir`
    (used by the lab path and the known-good cache).
    """
    # Enforce the allow-list on netlab's RESOLVED node devices (honors defaults/dotted keys/
    # groups), failing closed if devices can't be resolved — never treat "unknown" as allowed.
    resolved = resolved_node_devices(topology_yaml)
    if not resolved["ok"]:
        return _policy_fail(resolved["errors"] or ["topology devices could not be resolved"])
    devices = sorted(set(resolved["node_device"].values()))
    if not devices:
        return _policy_fail(["no devices resolved from topology; refusing to render"])
    allowed, rejected, reason = check_platforms(devices)
    if not allowed:
        return _policy_fail([reason], rejected=rejected)

    wd = new_workdir("nlmcp-render-")
    try:
        (wd / "topology.yml").write_text(topology_yaml)

        rc = run_netlab(["create", "topology.yml"], cwd=wd, timeout=timeout)
        if not rc.ok:
            return _fail("create", rc)

        ri = run_netlab(["initial", "-o", "configs"], cwd=wd, timeout=timeout)
        if not ri.ok:
            return _fail("initial", ri, clab=_read(wd / "clab.yml"))

        result = {
            "ok": True,
            "stage": "done",
            "errors": [],
            "per_node": _parse_configs(wd / "configs", nodes),
            "clab_yaml": _read(wd / "clab.yml"),
            "disclaimer": DISCLAIMER,
        }
        if keep_dir:
            result["workdir"] = str(wd)
        return result
    finally:
        if not keep_dir:
            cleanup(wd)
