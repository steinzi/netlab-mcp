"""Compatibility matrix: sqlite for queries + a committed YAML mirror for git-diff review."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..config import ARTIFACTS_DIR, STORE_DIR

_SCHEMA = Path(__file__).parent / "schema.sql"
_DB = STORE_DIR / "matrix.db"
_YAML = STORE_DIR / "matrix.yaml"

_WRITE_COLS = [
    "module", "scenario", "dut_platform", "peer_platforms", "provider",
    "netlab_version", "image", "stage_create", "stage_up", "stage_config",
    "stage_validate", "verdict", "topology_ref", "config_ref", "notes",
    "warnings", "source", "ts",
]
_CONFLICT = ["module", "scenario", "dut_platform", "peer_platforms", "provider", "netlab_version"]
_JSON_COLS = {"peer_platforms", "warnings"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets the MCP service read while a CLI sweep writes (and vice versa) instead of
    # the default rollback journal's whole-file lock; busy_timeout makes a contended writer
    # wait rather than immediately raising OperationalError up into a tool error.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(_SCHEMA.read_text())
    return conn


def _norm(rec: dict) -> dict:
    """Fill defaults and JSON-encode list columns."""
    r = dict(rec)
    r.setdefault("scenario", "")
    r.setdefault("provider", "clab")
    # ts is NOT NULL; callers (e.g. harvest) may pass an explicit None when the source
    # has no timestamp, so coerce any falsy value — setdefault alone wouldn't replace None.
    if not r.get("ts"):
        r["ts"] = _now()
    pp = r.get("peer_platforms", [])
    r["peer_platforms"] = json.dumps(sorted(pp)) if isinstance(pp, list) else (pp or "[]")
    w = r.get("warnings", [])
    r["warnings"] = json.dumps(w) if isinstance(w, list) else (w or "[]")
    for c in _WRITE_COLS:
        r.setdefault(c, None)
    return r


def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for c in _JSON_COLS:
        if isinstance(d.get(c), str):
            try:
                d[c] = json.loads(d[c])
            except json.JSONDecodeError:
                pass
    return d


def init_db() -> None:
    _connect().close()


def upsert(record: dict) -> None:
    """Insert or replace a verdict row (keyed by the version-scoped UNIQUE tuple), then
    refresh the YAML mirror."""
    r = _norm(record)
    placeholders = ", ".join("?" for _ in _WRITE_COLS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _WRITE_COLS if c not in _CONFLICT)
    sql = (
        f"INSERT INTO compat ({', '.join(_WRITE_COLS)}) VALUES ({placeholders}) "
        f"ON CONFLICT({', '.join(_CONFLICT)}) DO UPDATE SET {updates}"
    )
    conn = _connect()
    try:
        conn.execute(sql, [r[c] for c in _WRITE_COLS])
        conn.commit()
    finally:
        conn.close()
    dump_yaml()


def query(
    module: str | None = None,
    dut_platform: str | None = None,
    netlab_version: str | None = None,
    verdicts: list[str] | None = None,
) -> list[dict]:
    where, params = [], []
    if module:
        where.append("module = ?")
        params.append(module)
    if dut_platform:
        where.append("dut_platform = ?")
        params.append(dut_platform)
    if netlab_version:
        where.append("netlab_version = ?")
        params.append(netlab_version)
    if verdicts:
        placeholders = ", ".join("?" for _ in verdicts)
        where.append(f"verdict IN ({placeholders})")
        params.extend(verdicts)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM compat{clause} ORDER BY module, dut_platform, scenario, ts DESC",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_decode(r) for r in rows]


def get_known_good(module: str, platform: str, netlab_version: str | None = None) -> dict | None:
    """Most recent pass/warning row for module+platform, with cached topology + config inlined."""
    where = ["module = ?", "dut_platform = ?", "verdict IN ('pass','warning')"]
    params: list = [module, platform]
    if netlab_version:
        where.append("netlab_version = ?")
        params.append(netlab_version)
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT * FROM compat WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT 1",
            params,
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    rec = _decode(row)
    rec["topology_yaml"] = _load_text(rec.get("topology_ref"))
    rec["config"] = _load_json(rec.get("config_ref"))
    return rec


# --- artifact cache (topology + rendered config for known-good replay) ----------
_SLUG_MAX = 200  # keep the artifact dir well under the 255-byte filesystem component limit


def _slug(s: str) -> str:
    # The key is built from caller-controlled, unbounded fields (module, scenario, ...), so
    # bound the path component or an overlong value raises OSError(File name too long) when
    # the dir is created — which would crash a successful validation before it records.
    base = re.sub(r"[^a-zA-Z0-9_.-]+", "-", s).strip("-") or "run"
    if len(base) <= _SLUG_MAX:
        return base
    # Truncate but stay collision-resistant: append a hash of the full original key.
    digest = hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:12]
    return f"{base[:_SLUG_MAX - 13].rstrip('-')}-{digest}"


def cache_artifacts(key: str, topology_yaml: str, per_node: dict) -> tuple[str, str]:
    d = ARTIFACTS_DIR / _slug(key)
    d.mkdir(parents=True, exist_ok=True)
    topo = d / "topology.yml"
    cfg = d / "configs.json"
    topo.write_text(topology_yaml)
    cfg.write_text(json.dumps(per_node, indent=2))
    return str(topo), str(cfg)


def _load_text(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _load_json(path: str | None):
    txt = _load_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def dump_yaml() -> None:
    """Write the full matrix to a committed YAML file for human/PR review."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM compat ORDER BY module, dut_platform, scenario, netlab_version"
        ).fetchall()
    finally:
        conn.close()
    records = [_decode(r) for r in rows]
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    # Atomic write: every upsert rewrites this whole file, and concurrent writers (service +
    # CLI sweep, or two threads of one server) would otherwise interleave into a torn mirror.
    # mkstemp gives each writer a unique temp in the same dir; the rename is atomic.
    text = yaml.safe_dump(records, sort_keys=False, default_flow_style=False, width=100)
    fd, tmp = tempfile.mkstemp(dir=str(STORE_DIR), prefix=".matrix.", suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, _YAML)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
