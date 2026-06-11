"""End-to-end tests through the MCP tool layer (in-memory FastMCP client, no docker).

Drives the tools the way an MCP client would. Uses asyncio.run() inside sync tests, so
no pytest-asyncio plugin is needed (mirrors scripts/smoke_offline.py).
"""
import asyncio

import pytest
from fastmcp import Client

import netlab_mcp.server as s
from conftest import tool_data as _data  # noqa: E402
from netlab_mcp.store import matrix


def _run(go):
    return asyncio.run(go())


def test_generate_then_render():
    async def go():
        async with Client(s.mcp) as c:
            g = _data(await c.call_tool(
                "generate_topology", {"intent": "ebgp peering", "platforms": ["srlinux", "frr"]}))
            assert g["ok"] and g["module"] == "bgp" and g["valid"]
            r = _data(await c.call_tool("render_config", {"topology_yaml": g["topology_yaml"]}))
            assert r["ok"] and set(r["per_node"]) >= {"dut", "peer"} and r["disclaimer"]
    _run(go)


def test_generate_rejects_licensed_platform():
    async def go():
        async with Client(s.mcp) as c:
            g = _data(await c.call_tool("generate_topology",
                                        {"intent": "ebgp", "platforms": ["nxos"]}))
            assert g["ok"] is False and "nxos" in g["rejected"]
    _run(go)


def test_query_compatibility():
    async def go():
        async with Client(s.mcp) as c:
            q = _data(await c.call_tool("query_compatibility",
                                        {"module": "bgp", "platforms": ["srlinux"]}))
            assert q["ok"] and "srlinux" in q["declared"]
    _run(go)


def test_list_examples():
    async def go():
        async with Client(s.mcp) as c:
            e = _data(await c.call_tool("list_examples", {"module": "bgp"}))
            if not e.get("ok"):
                pytest.skip("netlab source examples not present (clone ipspace/netlab)")
            assert len(e["examples"]) > 0
    _run(go)


def test_report_failure_then_known_good_absent():
    async def go():
        async with Client(s.mcp) as c:
            rep = _data(await c.call_tool("report_failure", {
                "module": "bgp", "platforms": ["mcpfailnos", "frr"],
                "topology_yaml": "module: [bgp]\n", "error": "did not converge",
                "stage": "validate"}))
            assert rep["recorded"] is True
            kg = _data(await c.call_tool("get_known_good",
                                         {"module": "bgp", "platform": "mcpfailnos"}))
            assert kg["found"] is False  # a 'fail' row is never served as known-good
    _run(go)


def test_get_known_good_found_after_seed():
    matrix.upsert({"module": "bgp", "scenario": "mcp-seed", "dut_platform": "mcppassnos",
                   "peer_platforms": ["frr"], "netlab_version": "test-mcp",
                   "verdict": "pass", "stage_validate": "pass", "source": "lab"})

    async def go():
        async with Client(s.mcp) as c:
            kg = _data(await c.call_tool("get_known_good",
                                         {"module": "bgp", "platform": "mcppassnos"}))
            assert kg["found"] is True and kg["verdict"] == "pass" and kg["disclaimer"]
    _run(go)


def test_validate_in_lab_rejects_forbidden_device():
    async def go():
        async with Client(s.mcp) as c:
            topo = (
                "provider: clab\nmodule: [bgp]\n"
                "nodes:\n  dut: {device: srlinux, bgp.as: 65000}\n"
                "  evil: {device: nxos, bgp.as: 65100}\nlinks: [dut-evil]\n"
            )
            v = _data(await c.call_tool("validate_in_lab",
                                        {"topology_yaml": topo, "platforms": ["srlinux", "nxos"]}))
            assert v["verdict"] == "rejected" and "nxos" in v.get("rejected", [])
    _run(go)
