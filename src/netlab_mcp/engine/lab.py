"""Live lab path: deploy to containerlab, run `netlab validate`, record the verdict.

Gated behind a docker/containerlab probe and serialized by LAB_LOCK (shared docker daemon,
sudo on the containerlab hot path). The lab is always torn down in `finally`.
"""
from __future__ import annotations

from ..config import check_platforms
from ..models import DISCLAIMER, GOOD_VERDICTS, VALIDATE_EXIT
from ..store import matrix
from .probes import lab_available
from .render import _parse_configs, _read
from .runner import LAB_LOCK, cleanup, netlab_version, new_workdir, run_netlab
from .topo import devices_in_topology, node_device_map


def _record(
    *,
    module: str,
    scenario: str,
    dut_platform: str,
    peers: list[str],
    verdict: str,
    stages: dict[str, str | None],
    version: str,
    topology_yaml: str,
    per_node: dict,
    notes: str,
) -> dict:
    topology_ref = config_ref = None
    if verdict in GOOD_VERDICTS:
        key = f"{module}-{dut_platform}-{'-'.join(sorted(peers))}-{version}"
        topology_ref, config_ref = matrix.cache_artifacts(key, topology_yaml, per_node)
    rec = {
        "module": module,
        "scenario": scenario,
        "dut_platform": dut_platform,
        "peer_platforms": peers,
        "provider": "clab",
        "netlab_version": version,
        "image": None,
        **stages,
        "verdict": verdict,
        "topology_ref": topology_ref,
        "config_ref": config_ref,
        "notes": notes,
        "source": "lab",
    }
    matrix.upsert(rec)
    return rec


def validate_in_lab(
    topology_yaml: str,
    platforms: list[str],
    *,
    module: str = "bgp",
    scenario: str = "",
    dut_platform: str | None = None,
    keep_lab: bool = False,
    timeout_s: int = 600,
) -> dict:
    """Deploy + validate a topology in containerlab and persist the verdict."""
    # Policy checks run on the ACTUAL topology devices, before any capability probe or
    # deploy, so disallowed NOSes are rejected regardless of the caller's `platforms` claim.
    derived = devices_in_topology(topology_yaml)
    allowed, rejected, reason = check_platforms(sorted(derived))
    if not allowed:
        return {"ok": False, "verdict": "rejected", "rejected": rejected, "reason": reason,
                "derived_devices": sorted(derived), "disclaimer": DISCLAIMER}

    declared = set(platforms or [])
    if declared and declared != derived:
        return {
            "ok": False,
            "verdict": "mismatch",
            "reason": f"platforms argument {sorted(declared)} does not match the devices in "
                      f"the topology {sorted(derived)}; refusing to deploy.",
            "derived_devices": sorted(derived),
            "disclaimer": DISCLAIMER,
        }

    probe = lab_available()
    if not probe["ok"]:
        return {
            "ok": False,
            "verdict": "unavailable",
            "probe": probe,
            "disclaimer": DISCLAIMER,
            "note": "Lab validation requires docker + containerlab on a Linux host. "
                    "Offline tools (render_config, query_compatibility) work without it.",
        }

    # Roles recorded from the parsed topology, not the caller's platforms arg.
    nmap = node_device_map(topology_yaml)
    dut = nmap.get("dut") or dut_platform or (sorted(derived)[0] if derived else "unknown")
    peers = sorted({d for n, d in nmap.items() if n != "dut"}) or sorted(derived - {dut})
    scenario = scenario or f"{module}-{dut}-lab"
    version = netlab_version()

    with LAB_LOCK:
        wd = new_workdir("nlmcp-lab-")
        try:
            (wd / "topology.yml").write_text(topology_yaml)

            up = run_netlab(["up"], cwd=wd, timeout=timeout_s)
            if not up.ok:
                stages = {"stage_create": "pass", "stage_up": "fail",
                          "stage_config": None, "stage_validate": None}
                _record(module=module, scenario=scenario, dut_platform=dut, peers=peers,
                        verdict="deploy_failed", stages=stages, version=version,
                        topology_yaml=topology_yaml, per_node={},
                        notes="; ".join(up.error_lines())[:500])
                return {
                    "ok": False,
                    "verdict": "deploy_failed",
                    "stage": "up",
                    "errors": up.error_lines(),
                    "raw_output": up.stdout + up.stderr,
                    "harvested": True,
                    "disclaimer": DISCLAIMER,
                }

            # Render config text for the response (offline, from the snapshot up just built).
            ri = run_netlab(["initial", "-o", "configs"], cwd=wd, timeout=180)
            per_node = _parse_configs(wd / "configs", None) if ri.ok else {}

            val = run_netlab(["validate", "--dump", "result"], cwd=wd, timeout=timeout_s)
            verdict = VALIDATE_EXIT.get(val.returncode, "error")
            stages = {
                "stage_create": "pass",
                "stage_up": "pass",
                "stage_config": "pass" if ri.ok else "fail",
                "stage_validate": verdict if verdict in ("pass", "fail", "warning") else None,
            }
            _record(module=module, scenario=scenario, dut_platform=dut, peers=peers,
                    verdict=verdict, stages=stages, version=version,
                    topology_yaml=topology_yaml, per_node=per_node,
                    notes="; ".join(val.error_lines())[:500] if verdict != "pass" else "")

            return {
                "ok": verdict in GOOD_VERDICTS,
                "verdict": verdict,
                "netlab_version": version,
                "raw_validate_output": (val.stdout + val.stderr).strip(),
                "rendered_config": per_node,
                "clab_yaml": _read(wd / "clab.yml"),
                "harvested": True,
                "disclaimer": DISCLAIMER,
            }
        finally:
            run_netlab(["down", "--cleanup", "--force"], cwd=wd, timeout=300)
            if not keep_lab:
                cleanup(wd)
