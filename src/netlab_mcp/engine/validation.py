"""Device x module validation-plugin awareness.

netlab's `validate:` tests only assert anything when the anchoring node's device ships a
validation plugin for the module (netsim/validate/<module>/<device>.py). On any other
device the test is silently SKIPPED ("the results are not reliable"), which validate_in_lab
demotes to "no_tests". This module knows which device can assert which module, picks the
right node to anchor generated tests on, and explains the gap when no node qualifies.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache

# Modules we can emit a self-contained adjacency/session assertion for. Each spec builds
# one validate test anchored on `node`, asserting its relationship toward `neighbor`.
# Plugin call syntax verified live against netlab 26.06 (bgp_neighbor was already in use;
# ospf_neighbor(nodes.<peer>.ospf.router_id) passed on the lab box; isis_neighbor matches
# the adjacency by neighbor hostname). `wait` is numeric so the topology stays
# self-contained (no dependency on netlab's wait_times.yml); `wait_start` is NOT a valid
# validate attribute and must never be emitted.
MODULE_PLUGINS: dict[str, dict[str, str | int]] = {
    "bgp": {
        "test": "session",
        "description": "eBGP session between {node} and {neighbor} is established",
        "wait_msg": "Wait for the eBGP session to come up",
        "wait": 30,
        "plugin": "bgp_neighbor(node.bgp.neighbors,'{neighbor}')",
    },
    "ospf": {
        "test": "adjacency",
        "description": "OSPF adjacency between {node} and {neighbor} is Full",
        "wait_msg": "Wait for the OSPF adjacency to form",
        "wait": 90,
        "plugin": "ospf_neighbor(nodes.{neighbor}.ospf.router_id)",
    },
    "isis": {
        "test": "adjacency",
        "description": "IS-IS adjacency between {node} and {neighbor} is Up",
        "wait_msg": "Wait for the IS-IS adjacency to form",
        "wait": 90,
        "plugin": "isis_neighbor('{neighbor}')",
    },
}


@lru_cache(maxsize=256)
def device_can_assert(device: str, module: str) -> bool:
    """True when the installed netlab ships a validation plugin for device+module.

    netlab resolves `plugin: x(...)` in a validate test to netsim.validate.<module>.<device>,
    so the presence of that submodule IS the capability registry. Introspecting the installed
    package tracks the running netlab version instead of a frozen list.
    """
    if not device or not module or not all(p.isidentifier() for p in (device, module)):
        return False
    try:
        return importlib.util.find_spec(f"netsim.validate.{module}.{device}") is not None
    except (ImportError, ValueError):
        return False


def assertable_modules(device: str) -> list[str]:
    """Modules from MODULE_PLUGINS this device can anchor validation tests for."""
    return sorted(m for m in MODULE_PLUGINS if device_can_assert(device, m))


def pick_validation_node(node_device: dict[str, str], module: str) -> str | None:
    """Pick the node to anchor the generated validate test on, or None.

    Prefers a non-dut node (the test asserts TOWARD the dut, keeping the dut the subject
    under test), falling back to the dut itself; ties break on sorted node name so
    generated topologies are deterministic.
    """
    capable = [n for n, d in sorted(node_device.items()) if device_can_assert(d, module)]
    if not capable:
        return None
    non_dut = [n for n in capable if n != "dut"]
    return (non_dut or capable)[0]


def build_validate_block(module: str, node: str, neighbor: str) -> dict | None:
    """One-test `validate:` block for module, anchored on node, asserting toward neighbor."""
    spec = MODULE_PLUGINS.get(module)
    if spec is None:
        return None
    return {
        str(spec["test"]): {
            "description": str(spec["description"]).format(node=node, neighbor=neighbor),
            "wait_msg": str(spec["wait_msg"]),
            "wait": spec["wait"],
            "nodes": [node],
            "plugin": str(spec["plugin"]).format(neighbor=neighbor),
        }
    }


def capable_devices(module: str, devices: list[str] | None = None) -> list[str]:
    """Of `devices` (or a well-known set), those with a validation plugin for module."""
    pool = devices if devices is not None else _well_known_devices()
    return sorted({d for d in pool if device_can_assert(d, module)})


@lru_cache(maxsize=1)
def _well_known_devices() -> tuple[str, ...]:
    """Devices the installed netlab knows about, for suggestion text. Best-effort."""
    try:
        import pkgutil

        import netsim.devices  # type: ignore

        return tuple(sorted(
            m.name for m in pkgutil.iter_modules(netsim.devices.__path__)
            if not m.name.startswith("_") and m.name != "unknown"
        ))
    except Exception:
        return ("frr", "eos", "cumulus", "srlinux", "vyos", "linux")
