"""Unit tests for topogen validation-node selection across device orderings."""
import yaml

from netlab_mcp.engine import topogen


def test_eos_anchors_validation():
    # eos has a netlab BGP validation plugin; with dut=eos the test runs on dut.
    topo = yaml.safe_load(topogen.generate("ebgp", ["eos", "srlinux"])["topology_yaml"])
    sess = topo["validate"]["session"]
    assert sess["nodes"] == ["dut"]
    assert "'peer'" in sess["plugin"]


def test_no_capable_device_emits_no_validate_block():
    # neither linux node has a BGP validation plugin: no validate block + a warning.
    gen = topogen.generate("ebgp", ["linux", "linux"])
    topo = yaml.safe_load(gen["topology_yaml"])
    assert "validate" not in topo
    assert any("cannot be auto-verified" in w for w in gen["warnings"])
