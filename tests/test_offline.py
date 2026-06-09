"""Offline suite — no docker required. Exercises the real netlab render + the store."""
from pathlib import Path

import yaml
from conftest import FIXTURES

from netlab_mcp.config import check_platforms
from netlab_mcp.engine import compat, lab, render, topo, topogen, transform
from netlab_mcp.models import DISCLAIMER
from netlab_mcp.store import matrix

MVP = (FIXTURES / "mvp_bgp.yml").read_text()

# A topology that smuggles a forbidden NOS (nxos) past caller metadata.
FORBIDDEN = """\
provider: clab
module: [ bgp ]
nodes:
  dut: {device: srlinux, bgp.as: 65000}
  evil: {device: nxos, bgp.as: 65100}
links: [ dut-evil ]
"""

# Forbidden device via netlab's dotted-key default (literal key "defaults.device") with NO
# per-node device field — the bypass a literal `device:` scan misses.
DEFAULT_FORBIDDEN = (
    "provider: clab\nmodule: [bgp]\ndefaults.device: nxos\n"
    "nodes: {a: {bgp.as: 65000}, b: {bgp.as: 65100}}\nlinks: [a-b]\n"
)

# No device anywhere — netlab cannot resolve one; policy must fail closed.
NO_DEVICE = (
    "provider: clab\nmodule: [bgp]\n"
    "nodes: {a: {bgp.as: 65000}, b: {bgp.as: 65100}}\nlinks: [a-b]\n"
)

# Allowed node devices, but smuggles an external Docker tool (edgeshark) via `tools:` —
# a container-spawn vector the device allow-list alone does not cover.
TOOLS_TOPO = (
    "provider: clab\nmodule: [bgp]\n"
    "tools:\n  edgeshark:\n"
    "nodes:\n  dut: {device: srlinux, bgp.as: 65000}\n"
    "  peer: {device: frr, bgp.as: 65100}\nlinks: [dut-peer]\n"
)


def test_render_produces_real_config_for_both_platforms():
    out = render.render_config(MVP)
    assert out["ok"], out["errors"]
    assert set(out["per_node"]) >= {"dut", "peer"}
    # srlinux DUT: real BGP config with our AS.
    dut_cfg = "\n".join(out["per_node"]["dut"].values())
    assert "65000" in dut_cfg
    # frr peer: vtysh BGP config referencing the remote AS.
    peer_cfg = "\n".join(out["per_node"]["peer"].values())
    assert "router bgp" in peer_cfg.lower()
    # clab.yml carries the free images.
    assert out["clab_yaml"] and "srlinux" in out["clab_yaml"]
    assert out["disclaimer"] == DISCLAIMER


def test_render_filters_to_requested_nodes():
    out = render.render_config(MVP, nodes=["dut"])
    assert set(out["per_node"]) == {"dut"}


def test_generate_topology_is_parse_valid():
    gen = topogen.generate("ebgp peering", ["srlinux", "frr"])
    assert gen["module"] == "bgp"
    assert transform.validate_topology(gen["topology_yaml"])["ok"]


def test_bgp_validation_anchored_on_capable_node():
    # frr has a netlab BGP validation plugin, srlinux does not. The session test must
    # run on the frr node regardless of ordering, asserting the neighbor toward the
    # other node — otherwise netlab silently skips it and reports a false "pass".
    for plats, want_node, want_neighbor in (
        (["srlinux", "frr"], "peer", "dut"),   # peer=frr is capable
        (["frr", "srlinux"], "dut", "peer"),   # dut=frr is capable
    ):
        topo = yaml.safe_load(topogen.generate("ebgp", plats)["topology_yaml"])
        sess = topo["validate"]["session"]
        assert sess["nodes"] == [want_node], plats
        assert f"'{want_neighbor}'" in sess["plugin"], plats


def test_bgp_no_validation_when_no_capable_device():
    # Neither srlinux nor vyos ships a BGP validation plugin: emit NO validate block
    # (a skipped test would be recorded as a false pass) and warn instead.
    gen = topogen.generate("ebgp", ["srlinux", "vyos"])
    topo = yaml.safe_load(gen["topology_yaml"])
    assert "validate" not in topo
    assert any("cannot be auto-verified" in w for w in gen["warnings"])


def test_transform_rejects_garbage():
    bad = transform.validate_topology("this: [is, not, a, topology\n")
    assert not bad["ok"]
    assert bad["errors"]


def test_detect_module_keywords():
    assert topogen.detect_module("set up evpn vxlan") == "evpn"
    assert topogen.detect_module("two ospf routers") == "ospf"
    assert topogen.detect_module("just peer them") == "bgp"  # default


def test_allow_list_blocks_licensed_nos():
    ok, rejected, reason = check_platforms(["srlinux", "nxos"])
    assert not ok and "nxos" in rejected
    assert "srlinux" in check_platforms(["srlinux"])[2] or check_platforms(["srlinux"])[0]


def test_declared_support_lists_srlinux_bgp():
    res = compat.declared_support(module="bgp", platforms=["srlinux"])
    assert res["ok"], res.get("error")
    assert "srlinux" in res["data"]
    assert "bgp" in res["data"]["srlinux"]


def test_declared_support_multi_platform_filter():  # F1
    res = compat.declared_support(module="bgp", platforms=["frr", "srlinux"])
    assert res["ok"], res.get("error")
    assert set(res["data"]) == {"frr", "srlinux"}  # filtered, not the full ~33-device dump


def test_generate_topology_warns_on_unrecognized_intent():  # F2
    gen = topogen.generate("xyzzy frobnicate the wibble", ["srlinux", "frr"])
    assert gen["module"] == "bgp"
    assert any("defaulted to 'bgp'" in w for w in gen["warnings"])
    # a real keyword does NOT warn, and is echoed in notes
    ok = topogen.generate("set up ospf", ["frr", "vyos"])
    assert not any("defaulted" in w for w in ok["warnings"])
    assert any("ospf" in n for n in ok["notes"])


def test_validate_is_host_independent_for_vyos():  # F3
    # vyos clab def bind-mounts /lib/modules (absent on macOS); topology is still sound.
    gen = topogen.generate("ospf", ["frr", "vyos"])
    res = transform.validate_topology(gen["topology_yaml"])
    assert res["ok"], res["errors"]


def test_validate_surfaces_specific_netlab_error():  # F3b
    bad = (
        "provider: clab\nmodule: [bgp]\n"
        "nodes: {dut: {device: notarealnos, bgp.as: 65000}, "
        "peer: {device: frr, bgp.as: 65100}}\nlinks: [dut-peer]\n"
    )
    res = transform.validate_topology(bad)
    assert not res["ok"]
    assert any("notarealnos" in e for e in res["errors"]), res["errors"]


def test_matrix_roundtrip_and_known_good():
    matrix.upsert({
        "module": "bgp", "scenario": "unit-pass", "dut_platform": "srlinux",
        "peer_platforms": ["frr"], "netlab_version": "test-1",
        "verdict": "pass", "stage_validate": "pass", "source": "lab",
        "topology_ref": None, "config_ref": None,
    })
    rows = matrix.query(module="bgp", dut_platform="srlinux")
    assert any(r["scenario"] == "unit-pass" and r["verdict"] == "pass" for r in rows)
    good = matrix.get_known_good("bgp", "srlinux")
    assert good and good["verdict"] == "pass"


def test_report_failure_is_negative_feedback():
    matrix.upsert({
        "module": "bgp", "scenario": "reported-validate", "dut_platform": "vyos",
        "netlab_version": "test-1", "verdict": "fail", "source": "report_failure",
        "notes": "did not converge",
    })
    fails = matrix.query(module="bgp", dut_platform="vyos", verdicts=["fail"])
    assert fails and fails[0]["notes"] == "did not converge"
    # a failing combo must NOT be served as known-good
    assert matrix.get_known_good("bgp", "vyos") is None


def test_topo_devices_in_doc_is_informational():
    import yaml as _yaml
    assert topo.devices_in_doc(_yaml.safe_load(MVP)) == {"srlinux", "frr"}


def test_render_rejects_forbidden_device_embedded_in_yaml():
    out = render.render_config(FORBIDDEN)
    assert not out["ok"] and out["stage"] == "policy"
    assert "nxos" in out["rejected"]
    assert not out["per_node"]  # nothing rendered


def test_render_rejects_forbidden_device_hidden_in_group():
    topo_yaml = (
        "provider: clab\nmodule: [bgp]\n"
        "groups:\n  bad: {device: nxos, members: [r1]}\n"
        "nodes:\n  r1: {bgp.as: 65000}\n  r2: {device: srlinux, bgp.as: 65100}\n"
        "links: [r1-r2]\n"
    )
    out = render.render_config(topo_yaml)
    assert not out["ok"] and "nxos" in out["rejected"]


def test_validate_in_lab_rejects_forbidden_device_before_probe():
    # allow-list runs on derived topology devices, before the docker/containerlab probe
    out = lab.validate_in_lab(FORBIDDEN, ["srlinux", "nxos"], module="bgp")
    assert out["verdict"] == "rejected" and "nxos" in out["rejected"]


def test_validate_in_lab_rejects_platforms_topology_mismatch():
    only_srlinux = (
        "provider: clab\nmodule: [bgp]\n"
        "nodes:\n  dut: {device: srlinux, bgp.as: 65000}\n"
        "  p: {device: srlinux, bgp.as: 65100}\nlinks: [dut-p]\n"
    )
    out = lab.validate_in_lab(only_srlinux, ["srlinux", "frr"], module="bgp")
    assert out["verdict"] == "mismatch", out


# --- resolved-device enforcement (Codex round 2: default-device bypass) ---------
def test_resolved_devices_catches_dotted_default():
    res = transform.resolved_node_devices(DEFAULT_FORBIDDEN)
    assert res["ok"], res["errors"]
    assert set(res["node_device"].values()) == {"nxos"}  # resolved onto every node


def test_resolved_devices_fail_closed_when_no_device():
    res = transform.resolved_node_devices(NO_DEVICE)
    assert not res["ok"]  # netlab can't resolve a device -> caller must reject


def test_render_rejects_dotted_default_device():
    out = render.render_config(DEFAULT_FORBIDDEN)
    assert not out["ok"] and out["stage"] == "policy"
    assert "nxos" in out["rejected"]


def test_render_fails_closed_on_unresolvable_topology():
    out = render.render_config(NO_DEVICE)
    assert not out["ok"] and out["stage"] == "policy" and not out["per_node"]


def test_validate_in_lab_rejects_dotted_default_without_platforms():
    # no platforms arg => enforcement must come from the resolved topology, not metadata
    out = lab.validate_in_lab(DEFAULT_FORBIDDEN, [], module="bgp")
    assert out["verdict"] == "rejected" and "nxos" in out.get("rejected", [])


# --- external-tools spawn vector (Codex round 3) -------------------------------
def test_resolved_tools_detects_and_reports_none():
    assert "edgeshark" in transform.resolved_tools(TOOLS_TOPO)["tools"]
    none = transform.resolved_tools(MVP)
    assert none["ok"] and none["tools"] == []


def test_validate_in_lab_rejects_external_tools_before_deploy():
    out = lab.validate_in_lab(TOOLS_TOPO, ["srlinux", "frr"], module="bgp")
    assert out["verdict"] == "rejected" and "edgeshark" in out.get("tools", [])


def test_yaml_mirror_written():
    matrix.upsert({"module": "ospf", "dut_platform": "frr", "netlab_version": "test-1",
                   "verdict": "pass", "source": "lab"})
    mirror = Path(matrix._YAML)
    assert mirror.is_file() and "ospf" in mirror.read_text()
