"""Ingest netlab's `device-module-test` results.yaml into the matrix.

That harness writes one entry per test, keyed by test name, with per-stage booleans (or
{warning: [...]}) plus `_version`, `_timestamp`, `_image`, `_warning`. Device/provider are
external to the file (passed via -d/-p), so the caller supplies them.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import matrix


def _stage(val) -> str | None:
    if val is True:
        return "pass"
    if val is False:
        return "fail"
    if isinstance(val, dict) and "warning" in val:
        return "warning"
    return None


def _rollup(stages: dict[str, str | None]) -> str:
    vals = [v for v in stages.values() if v is not None]
    if not vals:
        return "partial"
    if "fail" in vals:
        return "fail"
    if stages.get("stage_validate") is None:
        return "partial"
    if "warning" in vals:
        return "warning"
    return "pass"


def harvest_results(
    results_path: str,
    module: str,
    dut_platform: str,
    provider: str = "clab",
    peer_platforms: list[str] | None = None,
) -> dict:
    """Parse a results.yaml and upsert one matrix row per test. Returns a small summary."""
    path = Path(results_path)
    if not path.is_file():
        return {"ok": False, "error": f"no such file: {results_path}", "ingested": 0}
    data = yaml.safe_load(path.read_text()) or {}

    ingested = 0
    for test_name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        stages = {
            "stage_create": _stage(entry.get("create")),
            "stage_up": _stage(entry.get("up")),
            "stage_config": _stage(entry.get("config")),
            "stage_validate": _stage(entry.get("validate")),
        }
        matrix.upsert(
            {
                "module": module,
                "scenario": test_name,
                "dut_platform": dut_platform,
                "peer_platforms": peer_platforms or [],
                "provider": provider,
                "netlab_version": str(entry.get("_version", "unknown")),
                "image": entry.get("_image"),
                **stages,
                "verdict": _rollup(stages),
                "warnings": entry.get("_warning") or [],
                "source": "harvest",
                "ts": str(entry.get("_timestamp")) if entry.get("_timestamp") else None,
            }
        )
        ingested += 1
    return {"ok": True, "ingested": ingested, "module": module, "dut_platform": dut_platform}
