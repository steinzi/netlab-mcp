"""Live lab path: deploy to containerlab, run `netlab validate`, record the verdict.

Gated behind a docker/containerlab probe and serialized by LAB_LOCK (shared docker daemon,
sudo on the containerlab hot path). The lab is always torn down in `finally`.
"""
from __future__ import annotations

from ..config import check_platforms
from ..models import DISCLAIMER, GOOD_VERDICTS, VALIDATE_EXIT
from ..store import matrix
from . import images, validation
from .probes import lab_available
from .render import _parse_configs, _read
from .runner import LAB_LOCK, cleanup, netlab_version, new_workdir, run_netlab
from .transform import resolved_node_devices, resolved_tools

# Bounds on the caller-supplied per-stage timeout. `timeout_s` gates `up` and `validate`,
# and the whole deploy holds LAB_LOCK — an unbounded value lets one call wedge every other
# lab request, so clamp it to a sane window.
MIN_TIMEOUT_S = 30
MAX_TIMEOUT_S = 1800


def _explain_no_tests(
    topology_yaml: str, module: str, node_device: dict[str, str], output: str,
) -> dict:
    """Turn a 'no_tests' verdict into {reason, suggestion} the caller can act on.

    Three distinct causes look identical from the exit code alone: the topology has no
    `validate:` block, the tests exist but the anchoring device has no validation plugin
    (netlab silently skips them), or netlab ran zero real tests for another reason.
    """
    capable = sorted(n for n, d in node_device.items()
                     if validation.device_can_assert(d, module))
    anchor_hint = (
        f"anchor the validate test on one of: {', '.join(capable)}" if capable
        else f"no node in this topology can assert {module}; add one with a device from: "
             f"{', '.join(validation.capable_devices(module)) or 'none in this netlab version'}"
    )

    if "validate:" not in topology_yaml:
        return {
            "reason": f"topology has no validate: block, so there are no tests for {module}",
            "suggestion": "regenerate with generate_topology (it adds a validate test when "
                          f"a capable device is present) or add one by hand; {anchor_hint}",
        }
    low = output.lower()
    if "cannot find validation plugin" in low or "test action not defined" in low:
        return {
            "reason": "validate tests exist but the node they run on has no netlab "
                      f"validation plugin for {module}, so they were skipped",
            "suggestion": anchor_hint,
        }
    return {
        "reason": "netlab ran zero real tests (skipped or unreliable results)",
        "suggestion": f"check raw_validate_output; {anchor_hint}",
    }


def _pull_failure_hint(errors: list[str], devices: set[str]) -> str | None:
    """When a deploy died fetching an image, point at locally loaded alternatives.

    generate_topology pins images, but caller-supplied / list_examples topologies are
    deliberately not mutated — so on hosts whose local-only (vrnetlab-built) tags differ
    from netlab's defaults, `netlab up` hits an unpullable image and the error reads like
    a broken host. Name the fix instead of leaving the caller to guess.
    """
    err_text = " ".join(errors).lower()
    if not any(m in err_text for m in ("pull", "not found", "manifest unknown", "no such image")):
        return None
    local = {d: img for d, img in images.device_image_map().items() if d in devices}
    if not local:
        return None
    return (
        "the deploy seems to have failed fetching a container image; these devices have "
        "locally loaded images — pin them in the topology via "
        "defaults.devices.<device>.clab.image: "
        + ", ".join(f"{d} -> {img}" for d, img in sorted(local.items()))
    )


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
        # scenario is part of the matrix UNIQUE key, so it belongs in the artifact key too —
        # otherwise two scenarios with the same module/dut/peers/version overwrite each
        # other's cached topology+config in one shared dir.
        key = f"{module}-{scenario}-{dut_platform}-{'-'.join(sorted(peers))}-{version}"
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
    timeout_s = max(MIN_TIMEOUT_S, min(timeout_s, MAX_TIMEOUT_S))
    # Policy checks run on netlab's RESOLVED node devices, before any probe or deploy, so
    # disallowed NOSes are rejected regardless of the caller's `platforms` claim — and we
    # fail closed when devices can't be resolved (no metadata-absence loophole).
    resolved = resolved_node_devices(topology_yaml)
    if not resolved["ok"]:
        return {"ok": False, "verdict": "invalid", "errors": resolved["errors"],
                "reason": "topology devices could not be resolved; refusing to deploy",
                "disclaimer": DISCLAIMER}
    node_device = resolved["node_device"]
    derived = set(node_device.values())
    if not derived:
        return {"ok": False, "verdict": "rejected",
                "reason": "no devices resolved from topology; refusing to deploy",
                "disclaimer": DISCLAIMER}

    allowed, rejected, reason = check_platforms(sorted(derived))
    if not allowed:
        return {"ok": False, "verdict": "rejected", "rejected": rejected, "reason": reason,
                "derived_devices": sorted(derived), "disclaimer": DISCLAIMER}

    declared = set(platforms or [])
    if declared and declared != derived:
        return {
            "ok": False,
            "verdict": "mismatch",
            "reason": f"platforms argument {sorted(declared)} does not match the resolved "
                      f"devices in the topology {sorted(derived)}; refusing to deploy.",
            "derived_devices": sorted(derived),
            "disclaimer": DISCLAIMER,
        }

    # External tools (edgeshark, nso, ...) run arbitrary Docker containers outside the NOS
    # allow-list during `netlab up`. Reject any topology that declares them — the device
    # allow-list alone does not cover this spawn vector. `--no-tools` below is the backstop.
    tools = resolved_tools(topology_yaml)
    if not tools["ok"]:
        # Could not resolve the tools section — fail closed rather than rely solely on the
        # `--no-tools` backstop below (the first inspect at L126 succeeded, so a failure here
        # is anomalous and we refuse instead of guessing "no tools").
        return {
            "ok": False,
            "verdict": "invalid",
            "reason": "could not resolve the topology's external tools; refusing to deploy",
            "errors": tools.get("errors", []),
            "disclaimer": DISCLAIMER,
        }
    if tools["tools"]:
        return {
            "ok": False,
            "verdict": "rejected",
            "reason": "topology declares external tools that start unreviewed Docker "
                      "containers outside the allowed image set; refusing to deploy. "
                      "Remove the 'tools:' section.",
            "tools": tools["tools"],
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

    # Roles recorded from netlab's resolved node->device map, not the caller's platforms arg.
    dut = node_device.get("dut") or dut_platform or (sorted(derived)[0] if derived else "unknown")
    peers = sorted({d for n, d in node_device.items() if n != "dut"}) or sorted(derived - {dut})
    scenario = scenario or f"{module}-{dut}-lab"
    version = netlab_version()

    with LAB_LOCK:
        wd = new_workdir("nlmcp-lab-")
        try:
            (wd / "topology.yml").write_text(topology_yaml)

            # --no-tools: hard backstop so external tools never start even if detection above
            # somehow misses one (defense in depth alongside the explicit reject).
            up = run_netlab(["up", "--no-tools"], cwd=wd, timeout=timeout_s)
            if not up.ok:
                stages = {"stage_create": "pass", "stage_up": "fail",
                          "stage_config": None, "stage_validate": None}
                _record(module=module, scenario=scenario, dut_platform=dut, peers=peers,
                        verdict="deploy_failed", stages=stages, version=version,
                        topology_yaml=topology_yaml, per_node={},
                        notes="; ".join(up.error_lines())[:500])
                result = {
                    "ok": False,
                    "verdict": "deploy_failed",
                    "stage": "up",
                    "errors": up.error_lines(),
                    "raw_output": up.stdout + up.stderr,
                    "harvested": True,
                    "disclaimer": DISCLAIMER,
                }
                hint = _pull_failure_hint(up.error_lines(), derived)
                if hint:
                    result["suggestion"] = hint
                return result

            # Render config text for the response (offline, from the snapshot up just built).
            ri = run_netlab(["initial", "-o", "configs"], cwd=wd, timeout=180)
            per_node = _parse_configs(wd / "configs", None) if ri.ok else {}

            val = run_netlab(["validate", "--dump", "result"], cwd=wd, timeout=timeout_s)
            verdict = VALIDATE_EXIT.get(val.returncode, "error")
            # Guard against a false "pass". `netlab validate` exits 0 when every test was
            # SKIPPED (e.g. the topology's validation plugin isn't implemented for the
            # target device), so the exit code alone can over-report. netlab flags it in
            # the output ("...the results are not reliable"); demote any pass/warning that
            # ran zero real tests to "no_tests" so it never caches as known-good. Matters
            # because validate_in_lab accepts arbitrary caller-supplied topologies.
            out_lower = (val.stdout + val.stderr).lower()
            if verdict in ("pass", "warning") and (
                "the results are not reliable" in out_lower
                or "tests passed: 0" in out_lower
            ):
                verdict = "no_tests"
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

            result = {
                "ok": verdict in GOOD_VERDICTS,
                "verdict": verdict,
                "netlab_version": version,
                "raw_validate_output": (val.stdout + val.stderr).strip(),
                "rendered_config": per_node,
                "clab_yaml": _read(wd / "clab.yml"),
                "harvested": True,
                "disclaimer": DISCLAIMER,
            }
            if verdict == "no_tests":
                result["no_tests"] = _explain_no_tests(
                    topology_yaml, module, node_device, val.stdout + val.stderr)
            return result
        finally:
            run_netlab(["down", "--cleanup", "--force"], cwd=wd, timeout=300)
            if not keep_lab:
                cleanup(wd)
