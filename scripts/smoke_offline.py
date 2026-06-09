"""End-to-end offline smoke through the MCP tool layer (no docker).

Drives the tools the way an LLM client would, via an in-memory FastMCP client.
Run: PYTHONPATH=src python scripts/smoke_offline.py
"""
import asyncio
import sys

from fastmcp import Client

import netlab_mcp.server as s


def _data(res):
    # fastmcp CallToolResult: prefer deserialized structured data
    for attr in ("data", "structured_content"):
        v = getattr(res, attr, None)
        if v is not None:
            return v
    return res


async def main() -> int:
    async with Client(s.mcp) as c:
        print("# 1. generate_topology(ebgp, [srlinux, frr])")
        g = _data(await c.call_tool("generate_topology",
                                    {"intent": "ebgp peering", "platforms": ["srlinux", "frr"]}))
        assert g["ok"] and g["valid"], g
        topo = g["topology_yaml"]
        print(f"   module={g['module']} valid={g['valid']}")

        print("# 2. render_config(topology)")
        r = _data(await c.call_tool("render_config", {"topology_yaml": topo}))
        assert r["ok"], r
        assert "65000" in "\n".join(r["per_node"]["dut"].values())
        assert "router bgp" in "\n".join(r["per_node"]["peer"].values()).lower()
        assert r["disclaimer"]
        print(f"   nodes={sorted(r['per_node'])} clab_image={'srlinux' in (r['clab_yaml'] or '')}")

        print("# 3. query_compatibility(bgp, [srlinux])")
        q = _data(await c.call_tool("query_compatibility",
                                    {"module": "bgp", "platforms": ["srlinux"]}))
        assert q["ok"] and "srlinux" in q["declared"], q
        print(f"   declared srlinux/bgp present; observed_rows={len(q['observed'])}")

        print("# 4. report_failure(demo negative feedback)")
        f = _data(await c.call_tool("report_failure", {
            "module": "bgp", "platforms": ["vyos", "frr"],
            "topology_yaml": topo, "error": "smoke demo failure", "stage": "validate"}))
        assert f["recorded"], f
        print(f"   recorded fail for {f['dut_platform']}")

        print("# 5. list_examples(bgp)")
        e = _data(await c.call_tool("list_examples", {"module": "bgp"}))
        assert e["ok"] and e["examples"], e
        print(f"   {len(e['examples'])} bgp example topologies indexed")

        # This is the lab tool; the offline smoke only asserts it returns a
        # well-formed, structured verdict (+ disclaimer) rather than crashing.
        # 'unavailable' on a box with no containerlab; 'deploy_failed' when
        # containerlab is present but can't deploy (e.g. too old); 'pass'/
        # 'warning' on a working lab host.
        print("# 6. validate_in_lab (structured verdict; 'unavailable' without containerlab)")
        v = _data(await c.call_tool("validate_in_lab",
                                    {"topology_yaml": topo, "platforms": ["srlinux", "frr"]}))
        print(f"   verdict={v['verdict']} reasons={v.get('probe', {}).get('reasons')}")
        assert v["verdict"] in ("unavailable", "deploy_failed", "pass", "warning"), v
        assert v["disclaimer"], v

    print("\nOK: offline MCP loop verified.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
