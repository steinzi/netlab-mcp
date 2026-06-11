"""MVP topology generator: intent + platforms -> a netlab topology YAML.

This is intentionally template-based (2-node labs). Full natural-language topology synthesis
(multi-node, role inference) is a later phase; netlab owns the hard data-model transform, so
even these small topologies render real, validated config.
"""
from __future__ import annotations

import yaml

from . import validation

# Modules we can scaffold a sensible starter lab for. Order matters for keyword detection
# (check more specific tokens first).
_KNOWN_MODULES = ["evpn", "vxlan", "ospf", "isis", "eigrp", "mpls", "vrf", "vlan", "bgp"]
_DEFAULT_PLATFORMS = ["srlinux", "frr"]


def match_module(intent: str) -> str | None:
    """Return the module keyword found in intent, or None if nothing matched."""
    low = (intent or "").lower()
    for m in _KNOWN_MODULES:
        if m in low:
            return m
    return None


def detect_module(intent: str) -> str:
    """Module from intent, defaulting to bgp when nothing matches."""
    return match_module(intent) or "bgp"


def generate(intent: str, platforms: list[str] | None) -> dict:
    matched = match_module(intent)
    module = matched or "bgp"
    plats = list(platforms) if platforms else list(_DEFAULT_PLATFORMS)
    dut = plats[0]
    peer = plats[1] if len(plats) > 1 else plats[0]

    notes: list[str] = []
    warnings = [
        "MVP generator is template-based (2-node lab). Treat the result as a starting point "
        "and refine attributes for your scenario.",
    ]
    if matched is None:
        warnings.append(
            "Intent did not match a known module keyword; defaulted to 'bgp'. "
            f"Name a module to be explicit (one of: {', '.join(_KNOWN_MODULES)})."
        )
    else:
        notes.append(f"Matched module '{module}' from the intent.")

    topo: dict = {"provider": "clab", "module": [module], "nodes": {}, "links": ["dut-peer"]}

    if module == "bgp":
        topo["nodes"] = {
            "dut": {"device": dut, "bgp": {"as": 65000}},
            "peer": {"device": peer, "bgp": {"as": 65100}},
        }
        notes.append("2-node eBGP lab: dut (AS 65000) <-> peer (AS 65100), IPv4 unicast.")
    elif module in ("ospf", "isis"):
        topo["nodes"] = {"dut": {"device": dut}, "peer": {"device": peer}}
        notes.append(f"2-node {module.upper()} lab in the default area/level.")
    else:
        topo["nodes"] = {"dut": {"device": dut}, "peer": {"device": peer}}
        notes.append(
            f"Generic 2-node '{module}' lab. This module often needs extra attributes "
            "(VLANs/VNIs/VRFs); add them or start from list_examples."
        )

    # Anchor the validate test on a node whose device ships a netlab validation plugin for
    # this module — on any other device the test is silently SKIPPED by `netlab validate`
    # (exit 0, "results are not reliable"), which would read as a false "pass". The check
    # is bidirectional (one capable endpoint confirms the adjacency/session), so a capable
    # peer is enough even when the dut itself can't assert. If no node is capable we emit
    # NO validation block and say so — structured in `validation`, human-readable in
    # `warnings` — rather than shipping a test that can only mislead.
    validation_info: dict = {"emitted": False, "module": module, "node": None, "device": None}
    node_device = {name: spec["device"] for name, spec in topo["nodes"].items()}
    if module in validation.MODULE_PLUGINS:
        val_node = validation.pick_validation_node(node_device, module)
        if val_node:
            neighbor = next(n for n in topo["nodes"] if n != val_node)
            topo["validate"] = validation.build_validate_block(module, val_node, neighbor)
            validation_info.update(emitted=True, node=val_node, device=node_device[val_node])
            notes.append(
                f"{module.upper()} validated from '{val_node}' ({node_device[val_node]}, "
                f"has a netlab {module} validation plugin)."
            )
        else:
            capable = validation.capable_devices(module)
            validation_info["warning"] = {
                "code": "no_validation_node",
                "module": module,
                "devices": sorted(set(node_device.values())),
                "capable_devices": capable,
                "suggestion": f"add a node with one of these devices to assert {module}: "
                              f"{', '.join(capable) or 'none in this netlab version'}",
            }
            warnings.append(
                f"No netlab {module} validation plugin for the requested platforms "
                f"({dut}, {peer}); only {', '.join(capable) or 'none'} can assert it. "
                f"The lab can be deployed but {module} cannot be auto-verified, so "
                "validate_in_lab will return an inconclusive verdict."
            )
    elif module in _KNOWN_MODULES:
        validation_info["warning"] = {
            "code": "module_not_auto_validated",
            "module": module,
            "suggestion": "add a validate: block by hand; see netlab's integration tests "
                          "(list_examples) for working test stanzas.",
        }

    return {
        "module": module,
        "platforms": [dut, peer],
        "topology_yaml": yaml.safe_dump(topo, sort_keys=False),
        "notes": notes,
        "warnings": warnings,
        "validation": validation_info,
    }
