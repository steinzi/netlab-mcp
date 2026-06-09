"""MVP topology generator: intent + platforms -> a netlab topology YAML.

This is intentionally template-based (2-node labs). Full natural-language topology synthesis
(multi-node, role inference) is a later phase; netlab owns the hard data-model transform, so
even these small topologies render real, validated config.
"""
from __future__ import annotations

import yaml

# Modules we can scaffold a sensible starter lab for. Order matters for keyword detection
# (check more specific tokens first).
_KNOWN_MODULES = ["evpn", "vxlan", "ospf", "isis", "eigrp", "mpls", "vrf", "vlan", "bgp"]
_DEFAULT_PLATFORMS = ["srlinux", "frr"]

# Devices that ship a netlab BGP validation plugin (netsim/validate/bgp/<device>.py).
# A `bgp_neighbor(...)` test on any other device is silently SKIPPED by `netlab validate`
# (exit 0, "results are not reliable") — which would otherwise be recorded as a false
# "pass". So the generated validation must run on one of these. Keep in sync with that dir.
_BGP_VALIDATION_DEVICES = frozenset({"frr", "eos"})


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
        # Run the session check from a node whose device has a netlab BGP validation
        # plugin, asserting its neighbor toward the other node. A BGP session is
        # bidirectional, so one capable endpoint confirms the whole session. If neither
        # device is capable we emit NO validation block (rather than one that silently
        # skips and reports a false "pass") and warn that the lab can't auto-verify.
        if peer in _BGP_VALIDATION_DEVICES:
            val_node, neighbor = "peer", "dut"
        elif dut in _BGP_VALIDATION_DEVICES:
            val_node, neighbor = "dut", "peer"
        else:
            val_node = neighbor = None

        if val_node:
            # Numeric wait keeps the topology self-contained (no dependency on netlab's
            # test wait_times.yml). bgp_neighbor() ships with netlab's bgp validation.
            topo["validate"] = {
                "session": {
                    "description": "eBGP session between dut and peer is established",
                    "wait_msg": "Wait for the eBGP session to come up",
                    "wait": 30,
                    "nodes": [val_node],
                    "plugin": f"bgp_neighbor(node.bgp.neighbors,'{neighbor}')",
                }
            }
            notes.append(
                f"BGP session validated from '{val_node}' "
                f"({topo['nodes'][val_node]['device']}, has a netlab BGP validation plugin)."
            )
        else:
            warnings.append(
                f"No netlab BGP validation plugin for the requested platforms "
                f"({dut}, {peer}); only {', '.join(sorted(_BGP_VALIDATION_DEVICES))} are "
                "supported. The lab can be deployed but the eBGP session cannot be "
                "auto-verified, so validate_in_lab will return an inconclusive verdict."
            )
    elif module in ("ospf", "isis"):
        topo["nodes"] = {"dut": {"device": dut}, "peer": {"device": peer}}
        notes.append(f"2-node {module.upper()} lab in the default area/level.")
    else:
        topo["nodes"] = {"dut": {"device": dut}, "peer": {"device": peer}}
        notes.append(
            f"Generic 2-node '{module}' lab. This module often needs extra attributes "
            "(VLANs/VNIs/VRFs); add them or start from list_examples."
        )

    return {
        "module": module,
        "platforms": [dut, peer],
        "topology_yaml": yaml.safe_dump(topo, sort_keys=False),
        "notes": notes,
        "warnings": warnings,
    }
