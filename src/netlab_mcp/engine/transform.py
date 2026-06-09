"""Validate a topology by parsing it through `netlab create` (no docker, no devices)."""
from __future__ import annotations

from .runner import cleanup, new_workdir, run_netlab


def validate_topology(topology_yaml: str, timeout: int = 120) -> dict:
    """Validate a topology's data model only. Returns {ok, errors, stdout, stderr}.

    Uses `netlab create -o yaml`, which runs the full parse + data-model transform but
    emits transformed YAML INSTEAD of provider files. That skips containerlab host checks
    (e.g. the `/lib/modules` bind that fails on macOS), so `ok` means "the topology is
    sound" regardless of the host — not "this host can launch it". Genuine data-model
    errors (unknown device, bad attribute, malformed YAML) still produce a non-zero exit.
    Run in a throwaway dir; artifacts discarded.
    """
    wd = new_workdir("nlmcp-xform-")
    try:
        (wd / "topology.yml").write_text(topology_yaml)
        r = run_netlab(["create", "topology.yml", "-o", "yaml"], cwd=wd, timeout=timeout)
        return {
            "ok": r.ok,
            "errors": [] if r.ok else r.error_lines(),
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    finally:
        cleanup(wd)
