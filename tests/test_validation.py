"""Unit tests for validation-plugin awareness (engine/validation.py + topogen + lab)."""
import yaml

from netlab_mcp.engine import topogen, validation
from netlab_mcp.engine.lab import _explain_no_tests


# --- device_can_assert: introspects the installed netlab ------------------------
def test_capability_matches_installed_plugin_registry():
    # Version-proof: compare against the installed netsim/validate tree itself instead of
    # hard-coding one netlab release's plugin inventory (CI floats within >=26.06,<27).
    from pathlib import Path

    import netsim.validate

    registry = Path(netsim.validate.__file__).parent
    for device in ("frr", "eos", "srlinux", "cumulus", "linux"):
        for module in validation.MODULE_PLUGINS:
            expected = (registry / module / f"{device}.py").is_file()
            assert validation.device_can_assert(device, module) is expected, (device, module)
    # canary: frr asserting ospf has held since netlab's validate framework existed —
    # if this goes, the whole auto-anchor feature needs a fresh look, so fail loudly.
    assert validation.device_can_assert("frr", "ospf")


def test_capability_rejects_garbage_without_raising():
    assert not validation.device_can_assert("", "ospf")
    assert not validation.device_can_assert("frr", "")
    assert not validation.device_can_assert("no-such-device", "ospf")
    assert not validation.device_can_assert("frr", "../../etc")


def test_pick_validation_node_prefers_non_dut(monkeypatch):
    # Selection logic only — capability is stubbed so the test can't drift with the
    # installed netlab's plugin inventory.
    monkeypatch.setattr(validation, "device_can_assert", lambda d, m: d == "capable")
    nd = {"dut": "capable", "peer": "capable"}
    assert validation.pick_validation_node(nd, "ospf") == "peer"
    nd = {"dut": "capable", "peer": "other"}
    assert validation.pick_validation_node(nd, "ospf") == "dut"
    nd = {"dut": "other", "peer": "other"}
    assert validation.pick_validation_node(nd, "ospf") is None


# --- topogen: module-generic validate emission ----------------------------------
def test_ospf_emits_validate_anchored_on_capable_peer():
    gen = topogen.generate("ospf two routers", ["srlinux", "frr"])
    topo = yaml.safe_load(gen["topology_yaml"])
    test = topo["validate"]["adjacency"]
    assert test["nodes"] == ["peer"]
    assert "nodes.dut.ospf.router_id" in test["plugin"]
    assert "wait_start" not in test
    assert gen["validation"]["emitted"] is True
    assert gen["validation"]["node"] == "peer"


def test_ospf_without_capable_device_warns_structured(monkeypatch):
    monkeypatch.setattr(validation, "device_can_assert", lambda d, m: False)
    gen = topogen.generate("ospf", ["srlinux", "srlinux"])
    topo = yaml.safe_load(gen["topology_yaml"])
    assert "validate" not in topo
    w = gen["validation"]["warning"]
    assert w["code"] == "no_validation_node"
    assert w["capable_devices"] == validation.capable_devices("ospf")
    assert any("cannot be auto-verified" in s for s in gen["warnings"])


def test_isis_validate_uses_hostname_match():
    gen = topogen.generate("isis core", ["frr", "frr"])
    topo = yaml.safe_load(gen["topology_yaml"])
    test = topo["validate"]["adjacency"]
    assert test["plugin"] == "isis_neighbor('dut')"


def test_unsupported_module_gets_manual_suggestion():
    gen = topogen.generate("vxlan fabric", ["frr", "frr"])
    topo = yaml.safe_load(gen["topology_yaml"])
    assert "validate" not in topo
    assert gen["validation"]["warning"]["code"] == "module_not_auto_validated"


# --- lab: no_tests classification ------------------------------------------------
def test_explain_no_tests_missing_block():
    out = _explain_no_tests("nodes:\n  dut:\n", "ospf", {"dut": "srlinux", "peer": "frr"}, "")
    assert "no validate: block" in out["reason"]
    assert "peer" in out["suggestion"]


def test_explain_no_tests_wrong_anchor():
    topo = "validate:\n  adj:\n    nodes: [dut]\n"
    msg = "Cannot find validation plugin for device srlinux"
    out = _explain_no_tests(topo, "ospf", {"dut": "srlinux", "peer": "frr"}, msg)
    assert "skipped" in out["reason"]
    assert "peer" in out["suggestion"]


def test_pull_failure_hint_names_local_images(monkeypatch):
    from netlab_mcp.engine import images, lab

    monkeypatch.setattr(images, "device_image_map",
                        lambda: {"nxos": "vrnetlab/cisco_n9kv:9.3.9"})
    hint = lab._pull_failure_hint(
        ["Error: failed to pull vrnetlab/vr-n9kv:9.3.8: not found"], {"nxos", "frr"})
    assert hint and "vrnetlab/cisco_n9kv:9.3.9" in hint
    assert lab._pull_failure_hint(["some ansible failure"], {"nxos"}) is None
