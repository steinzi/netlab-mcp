"""Topology inspection: pull the actual devices out of a topology before netlab touches it.

The platform allow-list must be enforced on what netlab will *render/deploy*, not on
caller-supplied metadata. A topology can name a device in several places (node, group,
defaults, node_data), so `devices_in_*` recursively collects every `device:` value, and
`node_device_map` resolves each node's effective device for role recording.
"""
from __future__ import annotations

import yaml


def _walk_devices(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "device" and isinstance(v, str):
                out.add(v)
            _walk_devices(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _walk_devices(x, out)


def devices_in_doc(doc) -> set[str]:
    """Every device named anywhere in a parsed topology dict."""
    out: set[str] = set()
    _walk_devices(doc or {}, out)
    return out


def devices_in_topology(topology_yaml: str) -> set[str]:
    """Every device named anywhere in a topology YAML string. Empty set on parse error."""
    try:
        doc = yaml.safe_load(topology_yaml) or {}
    except yaml.YAMLError:
        return set()
    return devices_in_doc(doc)


def node_device_map(topology_yaml: str) -> dict[str, str]:
    """node name -> effective device, resolving node/group/defaults precedence (best-effort)."""
    try:
        doc = yaml.safe_load(topology_yaml) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(doc, dict):
        return {}

    defaults = doc.get("defaults")
    default_dev = defaults.get("device") if isinstance(defaults, dict) else None

    group_dev: dict[str, str] = {}
    groups = doc.get("groups")
    if isinstance(groups, dict):
        for gd in groups.values():
            if isinstance(gd, dict) and isinstance(gd.get("device"), str):
                for m in gd.get("members") or []:
                    if isinstance(m, str):
                        group_dev[m] = gd["device"]

    result: dict[str, str] = {}

    def resolve(name: str, nd) -> None:
        dev = nd.get("device") if isinstance(nd, dict) else None
        dev = dev or group_dev.get(name) or default_dev
        if isinstance(dev, str):
            result[name] = dev

    nodes = doc.get("nodes")
    if isinstance(nodes, dict):
        for name, nd in nodes.items():
            resolve(name, nd)
    elif isinstance(nodes, list):
        for item in nodes:
            if isinstance(item, str):
                resolve(item, None)
            elif isinstance(item, dict):
                for name, nd in item.items():
                    resolve(name, nd)
    return result
