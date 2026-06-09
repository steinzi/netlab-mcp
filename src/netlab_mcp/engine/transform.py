"""Topology transform helpers: data-model validation + authoritative device resolution.

Both run netlab's transform without provider/host checks (no docker), so they work the same
on any host. Device resolution goes through netlab itself rather than scraping the raw YAML —
the raw YAML can name a device via dotted keys (`defaults.device: nxos`), groups, or netlab
defaults that a literal `device:` scan would miss.
"""
from __future__ import annotations

import json

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


def _json_after_banner(text: str):
    """Parse the JSON object after netlab's `[INFO] Using lab topology file ...` banner.

    The banner itself contains a '[' ("[INFO]"), so we anchor on the first '{' — the
    `nodes` inspect expression always yields a JSON object.
    """
    i = text.find("{")
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[i:])
        return obj
    except json.JSONDecodeError:
        return None


def resolved_node_devices(topology_yaml: str, timeout: int = 120) -> dict:
    """Resolve each node's EFFECTIVE device the way netlab does (defaults, dotted keys,
    groups), via `netlab inspect -t`. Host-independent — no containerlab bind checks.

    Returns {ok, node_device: {node: device}, errors}. `ok` is False when netlab cannot
    transform the topology (e.g. no device resolves anywhere) — callers MUST fail closed
    on a non-ok result or an empty device set rather than treating it as "nothing to check".
    """
    wd = new_workdir("nlmcp-resolve-")
    try:
        (wd / "topology.yml").write_text(topology_yaml)
        r = run_netlab(
            ["inspect", "-t", "topology.yml", "nodes", "--format", "json"],
            cwd=wd,
            timeout=timeout,
        )
        if not r.ok:
            return {"ok": False, "node_device": {}, "errors": r.error_lines()}
        data = _json_after_banner(r.stdout)
        if not isinstance(data, dict):
            return {"ok": False, "node_device": {},
                    "errors": ["could not parse 'netlab inspect' output"]}
        node_device = {
            name: v["device"]
            for name, v in data.items()
            if isinstance(v, dict) and isinstance(v.get("device"), str)
        }
        return {"ok": True, "node_device": node_device, "errors": []}
    finally:
        cleanup(wd)
