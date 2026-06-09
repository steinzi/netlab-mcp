"""Lightweight topology inspection for INFORMATIONAL use (e.g. listing example devices).

NOTE: this is a raw-YAML scan and is deliberately NOT used for policy. It only sees literal
`device:` values and misses netlab's dotted-key (`defaults.device: nxos`) and default
resolution. Allow-list enforcement uses `transform.resolved_node_devices`, which asks netlab
to resolve effective devices authoritatively.
"""
from __future__ import annotations


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
    """Literal `device:` values anywhere in a parsed topology dict (best-effort, info only)."""
    out: set[str] = set()
    _walk_devices(doc or {}, out)
    return out
