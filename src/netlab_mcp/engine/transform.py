"""Validate a topology by parsing it through `netlab create` (no docker, no devices)."""
from __future__ import annotations

from .runner import cleanup, new_workdir, run_netlab


def validate_topology(topology_yaml: str, timeout: int = 120) -> dict:
    """Parse + transform a topology. Returns {ok, errors, stdout, stderr}.

    `netlab create` performs the full data-model transform and writes provider files;
    a zero exit code means the topology is structurally valid and renderable. We run it
    in a throwaway dir and discard the artifacts.
    """
    wd = new_workdir("nlmcp-xform-")
    try:
        (wd / "topology.yml").write_text(topology_yaml)
        r = run_netlab(["create", "topology.yml"], cwd=wd, timeout=timeout)
        return {
            "ok": r.ok,
            "errors": [] if r.ok else r.error_lines(),
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    finally:
        cleanup(wd)
