"""Regression tests for the audit-hardening fixes."""
import asyncio
import time

from fastmcp import Client

import netlab_mcp.server as s
from conftest import tool_data as _data
from netlab_mcp.engine import images, lab, runner
from netlab_mcp.store import matrix


def _fake_netlab(tmp_path, body: str):
    f = tmp_path / "fake-netlab"
    f.write_text("#!/bin/sh\n" + body)
    f.chmod(0o755)
    return f


# --- runner: process-group timeout kill (the orphaned-grandchild hang) -----------
def test_timeout_kills_grandchildren(tmp_path, monkeypatch):
    marker = tmp_path / "alive"
    # fake netlab spawns a detached grandchild that keeps touching a marker, then blocks.
    fake = _fake_netlab(
        tmp_path,
        f"( while true; do touch {marker}; sleep 0.2; done ) &\nsleep 30\n",
    )
    monkeypatch.setenv("NETLAB_MCP_NETLAB_BIN", str(fake))
    runner.netlab_bin.cache_clear()
    try:
        r = runner.run_netlab(["x"], cwd=tmp_path, timeout=1)
        assert r.returncode == runner.TIMEOUT_RC
        # If the grandchild survived, the marker keeps getting newer; it must go quiet.
        time.sleep(0.5)
        m1 = marker.stat().st_mtime
        time.sleep(0.6)
        assert marker.stat().st_mtime == m1, "grandchild still running after timeout"
    finally:
        runner.netlab_bin.cache_clear()


# --- runner: child still dies if the group signal is denied (no hang) ------------
def test_terminate_group_kills_child_when_killpg_denied(monkeypatch):
    import subprocess as sp

    proc = sp.Popen(["sleep", "30"], start_new_session=True)

    def deny(*a):
        raise PermissionError("not permitted")
    monkeypatch.setattr(runner.os, "killpg", deny)
    runner._terminate_group(proc)
    # The direct child must be reaped despite killpg being denied, so a follow-up
    # communicate() can't hang on a still-running process.
    assert proc.wait(timeout=5) is not None


# --- runner: color forced off so JSON/marker parsing survives FORCE_COLOR --------
def test_color_forced_off(tmp_path, monkeypatch):
    fake = _fake_netlab(tmp_path, 'echo "NO_COLOR=$NO_COLOR FORCE_COLOR=${FORCE_COLOR:-unset}"\n')
    monkeypatch.setenv("FORCE_COLOR", "3")
    monkeypatch.setenv("NETLAB_MCP_NETLAB_BIN", str(fake))
    runner.netlab_bin.cache_clear()
    try:
        r = runner.run_netlab(["x"], cwd=tmp_path, timeout=10)
        assert "NO_COLOR=1" in r.stdout
        assert "FORCE_COLOR=unset" in r.stdout
    finally:
        runner.netlab_bin.cache_clear()


# --- images: non-mapping YAML no longer crashes ----------------------------------
def test_default_images_handles_nonmapping_yaml(monkeypatch):
    def fake_run(*a, **k):
        return runner.RunResult(["netlab"], 0, "just a bare string", "")
    monkeypatch.setattr(images, "run_netlab", fake_run)
    images._netlab_default_clab_images.cache_clear()
    try:
        assert images._netlab_default_clab_images() == {}
    finally:
        images._netlab_default_clab_images.cache_clear()


# --- server: list_examples rejects path traversal --------------------------------
def test_list_examples_rejects_traversal(tmp_path, monkeypatch):
    (tmp_path / "bgp").mkdir()
    monkeypatch.setattr(s, "NETLAB_EXAMPLES", tmp_path)

    async def go():
        async with Client(s.mcp) as c:
            out = _data(await c.call_tool("list_examples", {"module": "../../../etc"}))
            assert out["ok"] is False
            assert "invalid" in out["error"].lower()
            ok = _data(await c.call_tool("list_examples", {"module": "bgp"}))
            assert ok["ok"] is True  # legit single component still works
    asyncio.run(go())


# --- lab: fail closed when the tools section can't be resolved -------------------
def test_validate_in_lab_fails_closed_on_unresolvable_tools(monkeypatch):
    monkeypatch.setattr(lab, "resolved_node_devices",
                        lambda y: {"ok": True, "node_device": {"dut": "frr"}, "errors": []})
    monkeypatch.setattr(lab, "resolved_tools",
                        lambda y: {"ok": False, "tools": [], "errors": ["inspect boom"]})
    out = lab.validate_in_lab("nodes:\n  dut:\n    device: frr\n", ["frr"], module="bgp")
    assert out["verdict"] == "invalid"
    assert "inspect boom" in out["errors"]


# --- lab: timeout_s is clamped before it reaches the subprocess ------------------
def test_timeout_s_clamped(monkeypatch):
    seen = []

    def fake_run(args, cwd, timeout=120, **k):
        seen.append((args[0] if args else "", timeout))
        return runner.RunResult(["netlab", *args], 1, "", "deploy fail")
    monkeypatch.setattr(lab, "resolved_node_devices",
                        lambda y: {"ok": True, "node_device": {"dut": "frr"}, "errors": []})
    monkeypatch.setattr(lab, "resolved_tools",
                        lambda y: {"ok": True, "tools": [], "errors": []})
    monkeypatch.setattr(lab, "lab_available",
                        lambda: {"ok": True, "docker": True, "containerlab": True, "reasons": []})
    monkeypatch.setattr(lab, "netlab_version", lambda: "26.06")
    monkeypatch.setattr(lab, "run_netlab", fake_run)
    lab.validate_in_lab("nodes:\n  dut:\n    device: frr\n", ["frr"], timeout_s=10**9)
    up_timeouts = [t for name, t in seen if name == "up"]
    assert up_timeouts and all(t <= lab.MAX_TIMEOUT_S for t in up_timeouts)


# --- store: WAL + atomic mirror --------------------------------------------------
def test_connect_enables_wal():
    matrix.init_db()
    conn = matrix._connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_dump_yaml_atomic_no_tmp_left():
    from netlab_mcp.config import STORE_DIR
    matrix.upsert({"module": "t", "scenario": "s", "dut_platform": "frr",
                   "peer_platforms": ["frr"], "netlab_version": "x",
                   "verdict": "fail", "source": "test"})
    assert not list(STORE_DIR.glob("*.tmp"))
    assert (STORE_DIR / "matrix.yaml").is_file()


# --- lab: artifact key includes scenario (no cross-scenario overwrite) -----------
def test_artifact_key_includes_scenario():
    r1 = lab._record(module="bgp", scenario="scenA", dut_platform="frr", peers=["frr"],
                     verdict="pass", stages={}, version="26.06",
                     topology_yaml="a", per_node={"dut": {}}, notes="")
    r2 = lab._record(module="bgp", scenario="scenB", dut_platform="frr", peers=["frr"],
                     verdict="pass", stages={}, version="26.06",
                     topology_yaml="b", per_node={"dut": {}}, notes="")
    assert r1["topology_ref"] != r2["topology_ref"]


def test_overlong_scenario_still_records():
    # A caller-supplied scenario long enough to blow the filesystem name limit must not
    # crash a successful run — the artifact dir name is bounded (and stays collision-safe).
    from pathlib import Path
    rec = lab._record(module="bgp", scenario="s" * 400, dut_platform="frr", peers=["frr"],
                      verdict="pass", stages={}, version="26.06",
                      topology_yaml="x", per_node={"dut": {}}, notes="")
    assert rec["topology_ref"] and Path(rec["topology_ref"]).is_file()
    assert len(Path(rec["topology_ref"]).parent.name) <= 200


def test_slug_bounds_length_and_stays_unique():
    a = matrix._slug("m-" + "z" * 400 + "-A")
    b = matrix._slug("m-" + "z" * 400 + "-B")
    assert len(a) <= 200 and len(b) <= 200
    assert a != b  # distinct keys keep distinct slugs despite truncation
