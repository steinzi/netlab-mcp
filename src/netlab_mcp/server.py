"""netlab-mcp FastMCP server: expose netlab's validated outputs to an LLM.

Offline tools (fast, no docker): generate_topology, render_config, query_compatibility,
get_known_good, list_examples, report_failure.
Lab tool (needs docker + containerlab): validate_in_lab.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastmcp import FastMCP

from .config import NETLAB_EXAMPLES, allowed_platforms, check_platforms
from .engine import compat, images, lab, probes, render, topo, topogen, transform, validation
from .engine.runner import netlab_version
from .models import DISCLAIMER
from .store import matrix


def _auth_from_env():
    """Optional static bearer auth: NETLAB_MCP_TOKEN or NETLAB_MCP_TOKEN_FILE.

    The file form keeps the secret out of `systemctl show`/process env dumps. No token
    set -> no auth layer (stdio use, or an external gate like a reverse proxy).
    """
    token = (os.environ.get("NETLAB_MCP_TOKEN") or "").strip()
    token_file = os.environ.get("NETLAB_MCP_TOKEN_FILE")
    if not token and token_file:
        try:
            token = Path(token_file).read_text().strip()
        except OSError as e:
            raise SystemExit(f"cannot read NETLAB_MCP_TOKEN_FILE {token_file!r}: {e}") from e
    if not token:
        return None
    from fastmcp.server.auth import StaticTokenVerifier

    return StaticTokenVerifier(tokens={token: {"client_id": "netlab-mcp"}})


mcp = FastMCP("netlab-mcp", auth=_auth_from_env())


# --- offline tools -------------------------------------------------------------
@mcp.tool
def generate_topology(intent: str, platforms: list[str] | None = None) -> dict:
    """Turn an intent + target platforms into a netlab topology YAML (parse-validated).

    intent: free text, e.g. "ebgp peering" or "ospf two routers". The module is inferred.
    platforms: NOS list, dut first (MVP free set: srlinux, frr, cumulus, vyos, linux).
    Feed the returned `topology_yaml` to render_config or validate_in_lab.
    """
    platforms = platforms or []
    ok, rejected, reason = check_platforms(platforms)
    if not ok:
        return {"ok": False, "error": reason, "rejected": rejected,
                "allowed_platforms": sorted(allowed_platforms())}

    gen = topogen.generate(intent, platforms)
    check = transform.validate_topology(gen["topology_yaml"])
    return {
        "ok": check["ok"],
        "module": gen["module"],
        "platforms": gen["platforms"],
        "topology_yaml": gen["topology_yaml"],
        "valid": check["ok"],
        "validation_errors": check["errors"],
        "notes": gen["notes"],
        "warnings": gen["warnings"],
        "validation": gen["validation"],
    }


@mcp.tool
def render_config(topology_yaml: str, nodes: list[str] | None = None) -> dict:
    """Render real per-device config from a netlab topology — offline, no containers.

    Returns {per_node: {node: {module: config_text}}, clab_yaml, disclaimer}. This is the
    netlab data-model transform + Jinja2 render; the config matches what would deploy.
    """
    return render.render_config(topology_yaml, nodes)


@mcp.tool
def query_compatibility(module: str | None = None, platforms: list[str] | None = None) -> dict:
    """What netlab *declares* a platform supports, overlaid with what was *observed* in the lab.

    `declared` comes from netlab; `observed` comes from prior validate_in_lab/harvest runs.
    `conflicts` flags cells declared-supported but observed-failing for the current version.
    """
    platforms = platforms or []
    declared = compat.declared_support(module=module, platforms=platforms or None)

    observed = matrix.query(
        module=module,
        dut_platform=(platforms[0] if len(platforms) == 1 else None),
    )

    version = netlab_version()
    conflicts = []
    decl_data = declared.get("data", {}) if declared.get("ok") else {}
    for row in observed:
        if row["verdict"] in ("fail", "deploy_failed") and row["netlab_version"] == version:
            dev = row["dut_platform"]
            mod = row["module"]
            if mod in (decl_data.get(dev, {}) or {}):
                conflicts.append(
                    f"{dev}/{mod}: netlab declares support but lab verdict is "
                    f"'{row['verdict']}' (scenario {row['scenario']}, netlab {version})"
                )

    # Declared support says a platform RUNS a module; it says nothing about whether the
    # platform can ASSERT it in `netlab validate`. Surface that separately so callers see
    # "srlinux runs ospf but can't auto-verify it" before deploying.
    if module:
        can_assert = {p: validation.device_can_assert(p, module) for p in platforms}
    else:
        can_assert = {p: validation.assertable_modules(p) for p in platforms}

    return {
        "ok": declared.get("ok", False),
        "netlab_version": version,
        "declared": decl_data,
        "declared_error": declared.get("error"),
        "validation": {
            "can_assert": can_assert,
            "note": "true = device ships a netlab validation plugin for the module; "
                    "anchor generated validate tests on a capable device.",
        },
        "observed": observed,
        "conflicts": conflicts,
    }


@mcp.tool
def get_known_good(module: str, platform: str, netlab_version: str | None = None) -> dict:
    """Return a previously lab-passed topology + rendered config for module+platform, if any."""
    rec = matrix.get_known_good(module, platform, netlab_version)
    if not rec:
        return {"found": False, "module": module, "platform": platform,
                "hint": "Run validate_in_lab to produce a known-good record."}
    return {
        "found": True,
        "verdict": rec["verdict"],
        "netlab_version": rec["netlab_version"],
        "last_validated": rec["ts"],
        "scenario": rec["scenario"],
        "peer_platforms": rec["peer_platforms"],
        "topology_yaml": rec.get("topology_yaml"),
        "config": rec.get("config"),
        "disclaimer": DISCLAIMER,
    }


@mcp.tool
def list_examples(module: str | None = None) -> dict:
    """Index netlab's integration test topologies (real, maintained multi-platform scenarios).

    With no module: list available modules + counts. With a module: list its scenarios.
    """
    base = NETLAB_EXAMPLES
    if not base.is_dir():
        return {"ok": False, "error": f"examples dir not found: {base}"}

    if not module:
        modules = sorted(
            p.name for p in base.iterdir()
            if p.is_dir() and any(p.glob("*.yml"))
        )
        return {"ok": True, "modules": modules}

    mod_dir = base / module
    if not mod_dir.is_dir():
        return {"ok": False, "error": f"no examples for module '{module}'"}

    examples = []
    for f in sorted(mod_dir.glob("*.yml")):
        info = {"name": f.stem, "path": str(f), "modules": [], "devices": []}
        try:
            doc = yaml.safe_load(f.read_text()) or {}
            mod = doc.get("module")
            info["modules"] = mod if isinstance(mod, list) else ([mod] if mod else [])
            info["devices"] = sorted(topo.devices_in_doc(doc))
            info["message"] = (doc.get("message") or "").strip().splitlines()[:1]
        except (yaml.YAMLError, OSError):
            pass
        examples.append(info)
    return {"ok": True, "module": module, "examples": examples}


@mcp.tool
def report_failure(
    module: str,
    platforms: list[str],
    topology_yaml: str,
    error: str,
    stage: str = "unknown",
) -> dict:
    """Record a negative result (a combo that did not work) into the compatibility matrix."""
    dut = platforms[0] if platforms else "unknown"
    peers = platforms[1:] if len(platforms) > 1 else []
    matrix.upsert({
        "module": module,
        "scenario": f"reported-{stage}",
        "dut_platform": dut,
        "peer_platforms": peers,
        "netlab_version": netlab_version(),
        "verdict": "fail",
        "stage_validate": "fail" if stage in ("validate", "unknown") else None,
        "notes": error[:1000],
        "source": "report_failure",
    })
    return {"recorded": True, "module": module, "dut_platform": dut, "stage": stage}


@mcp.tool
def host_check() -> dict:
    """Diagnose this host's lab readiness in one call — run this first when anything fails.

    Reports docker/containerlab availability + versions, the netlab version, which
    platforms are allowed, which devices have locally loaded images (deployable without a
    pull), and which devices can anchor validate tests per module.
    """
    probe = probes.lab_available()
    image_map = images.device_image_map()
    try:
        nl_version = netlab_version()
    except RuntimeError as e:  # doctor must diagnose a netlab-less host, not crash on it
        nl_version = None
        probe = {**probe, "ok": False, "reasons": [*probe["reasons"], str(e)]}
    if nl_version == "unknown":  # binary resolved but does not run (bad NETLAB_MCP_NETLAB_BIN?)
        probe = {**probe, "ok": False,
                 "reasons": [*probe["reasons"], "netlab executable does not run or reports "
                                                "no version; check NETLAB_MCP_NETLAB_BIN"]}
    return {
        "ok": probe["ok"],
        "lab_available": probe,
        "versions": {"netlab": nl_version, **probes.tool_versions()},
        "allowed_platforms": sorted(allowed_platforms()),
        "installed_device_images": image_map,
        "validation_plugins": {
            module: validation.capable_devices(module)
            for module in sorted(validation.MODULE_PLUGINS)
        },
    }


# --- lab tool ------------------------------------------------------------------
@mcp.tool
def validate_in_lab(
    topology_yaml: str,
    platforms: list[str],
    module: str = "bgp",
    scenario: str = "",
    keep_lab: bool = False,
    timeout_s: int = 600,
) -> dict:
    """Deploy a topology to containerlab, run `netlab validate`, and record the verdict.

    Requires docker + containerlab on a Linux host. Returns the verdict (pass/fail/warning),
    rendered config, raw validate output, and persists a version-scoped matrix row. The lab is
    always torn down afterward. On a host without containerlab this returns verdict
    "unavailable" rather than failing.
    """
    return lab.validate_in_lab(
        topology_yaml, platforms, module=module, scenario=scenario,
        keep_lab=keep_lab, timeout_s=timeout_s,
    )


# --- health (HTTP transport only) -----------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(request):  # noqa: ANN001 - starlette Request, kept import-light
    """Unauthenticated liveness probe for funnels/uptime checks.

    Deliberately cheap and non-sensitive: no image list, no paths, and the docker probe
    is cached (~30s) so polling can't fork subprocesses per hit. The probe and the
    first-call netlab version both shell out, so they run in a worker thread — blocking
    the event loop here would stall every other request, /mcp included.
    """
    import anyio.to_thread
    from starlette.responses import JSONResponse

    version = await anyio.to_thread.run_sync(netlab_version)
    probe = await anyio.to_thread.run_sync(probes.lab_available_cached)
    return JSONResponse({
        "ok": True,
        "netlab_version": version,
        "lab_available": probe["ok"],
    })


# --- entrypoint ----------------------------------------------------------------
def main() -> None:
    """Run over stdio (default) or streamable HTTP.

    NETLAB_MCP_TRANSPORT=http serves /mcp on NETLAB_MCP_HOST:NETLAB_MCP_PORT
    (default 127.0.0.1:8000). Combine with NETLAB_MCP_TOKEN[_FILE] for bearer auth —
    mandatory if the host is anything other than loopback, since validate_in_lab reaches
    docker/sudo on this machine.
    """
    matrix.init_db()
    transport = (os.environ.get("NETLAB_MCP_TRANSPORT") or "stdio").strip().lower()
    if transport in ("http", "streamable-http"):
        host = os.environ.get("NETLAB_MCP_HOST", "127.0.0.1")
        port_raw = os.environ.get("NETLAB_MCP_PORT", "8000")
        try:
            port = int(port_raw)
        except ValueError:
            raise SystemExit(f"NETLAB_MCP_PORT must be a number, got {port_raw!r}") from None
        if host not in ("127.0.0.1", "localhost", "::1") and mcp.auth is None:
            raise SystemExit(
                "refusing to bind HTTP on a non-loopback host without auth; "
                "set NETLAB_MCP_TOKEN or NETLAB_MCP_TOKEN_FILE (or bind to 127.0.0.1)."
            )
        mcp.run(transport="http", host=host, port=port)
    elif transport == "stdio":
        mcp.run()
    else:
        raise SystemExit(f"unknown NETLAB_MCP_TRANSPORT '{transport}' (use stdio or http)")


if __name__ == "__main__":
    main()
