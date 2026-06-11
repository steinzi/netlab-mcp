"""Unit tests for host-image awareness (engine/images.py) and the platform gate."""
import yaml

from netlab_mcp import config
from netlab_mcp.engine import images, topogen


def _local(monkeypatch, repos):
    monkeypatch.setattr(images, "installed_images", lambda refresh=False: repos)


def _defaults(monkeypatch, mapping):
    monkeypatch.setattr(images, "_netlab_default_clab_images", lambda: mapping)


def test_default_tag_preferred_when_loaded(monkeypatch):
    _local(monkeypatch, {"quay.io/frrouting/frr": {"10.6.1", "latest"}})
    _defaults(monkeypatch, {"frr": "quay.io/frrouting/frr:10.6.1"})
    assert images.device_image_map() == {"frr": "quay.io/frrouting/frr:10.6.1"}


def test_falls_back_to_highest_loaded_tag(monkeypatch):
    _local(monkeypatch, {"vrnetlab/vr-fortios": {"7.6.2"}})
    _defaults(monkeypatch, {"fortios": "vrnetlab/vr-fortios:7.4.8"})
    assert images.device_image_map() == {"fortios": "vrnetlab/vr-fortios:7.6.2"}


def test_explicit_version_beats_latest(monkeypatch):
    _local(monkeypatch, {"ghcr.io/nokia/srlinux": {"latest", "26.3.2"}})
    _defaults(monkeypatch, {"srlinux": "ghcr.io/nokia/srlinux:25.0.0"})
    assert images.device_image_map() == {"srlinux": "ghcr.io/nokia/srlinux:26.3.2"}


def test_extra_repos_cover_renamed_vrnetlab_builds(monkeypatch):
    # netlab 26.06 maps nxos to vrnetlab/vr-n9kv; modern hellt builds name it cisco_n9kv.
    _local(monkeypatch, {"vrnetlab/cisco_n9kv": {"9.3.9"}})
    _defaults(monkeypatch, {"nxos": "vrnetlab/vr-n9kv:9.3.8"})
    assert images.device_image_map() == {"nxos": "vrnetlab/cisco_n9kv:9.3.9"}


def test_iol_l2_tags_split_by_device(monkeypatch):
    _local(monkeypatch, {"vrnetlab/cisco_iol": {"17.12.01", "l2-17.12.01"}})
    _defaults(monkeypatch, {
        "iol": "vrnetlab/cisco_iol:17.16.01a",
        "ioll2": "vrnetlab/cisco_iol:L2-17.16.01a",
    })
    out = images.device_image_map()
    assert out["iol"] == "vrnetlab/cisco_iol:17.12.01"
    assert out["ioll2"] == "vrnetlab/cisco_iol:l2-17.12.01"


def test_no_docker_means_no_map(monkeypatch):
    _local(monkeypatch, {})
    assert images.device_image_map() == {}


# --- platform gate ---------------------------------------------------------------
def test_gate_default_unchanged(monkeypatch):
    monkeypatch.delenv("NETLAB_MCP_PLATFORMS", raising=False)
    monkeypatch.delenv("NETLAB_MCP_ALLOW_INSTALLED", raising=False)
    assert config.allowed_platforms() == set(config.FREE_PLATFORMS)
    ok, rejected, reason = config.check_platforms(["nxos"])
    assert not ok and rejected == ["nxos"]
    assert "NETLAB_MCP_ALLOW_INSTALLED" in reason


def test_gate_csv_override(monkeypatch):
    monkeypatch.setenv("NETLAB_MCP_PLATFORMS", "nxos, iosxr")
    ok, rejected, _ = config.check_platforms(["nxos", "iosxr", "frr"])
    assert ok and not rejected


def test_gate_allow_installed(monkeypatch):
    monkeypatch.setenv("NETLAB_MCP_ALLOW_INSTALLED", "1")
    monkeypatch.delenv("NETLAB_MCP_PLATFORMS", raising=False)
    from netlab_mcp.engine import images as im
    monkeypatch.setattr(im, "device_image_map", lambda: {"nxos": "vrnetlab/cisco_n9kv:9.3.9"})
    assert "nxos" in config.allowed_platforms()
    assert "junos" not in config.allowed_platforms()


# --- topogen pinning --------------------------------------------------------------
def test_topogen_pins_loaded_images(monkeypatch):
    monkeypatch.setattr(images, "device_image_map",
                        lambda: {"frr": "quay.io/frrouting/frr:10.6.1"})
    gen = topogen.generate("ospf", ["srlinux", "frr"])
    topo = yaml.safe_load(gen["topology_yaml"])
    assert topo["defaults"]["devices"]["frr"]["clab"]["image"] == "quay.io/frrouting/frr:10.6.1"
    assert "srlinux" not in topo["defaults"]["devices"]
    assert any("Pinned to locally loaded images" in n for n in gen["notes"])


def test_topogen_no_pin_without_images(monkeypatch):
    monkeypatch.setattr(images, "device_image_map", lambda: {})
    topo = yaml.safe_load(topogen.generate("ospf", ["srlinux", "frr"])["topology_yaml"])
    assert "defaults" not in topo


def test_default_images_swallow_missing_netlab(monkeypatch):
    # The doctor path must survive a host where the netlab binary cannot resolve.

    def boom(*a, **k):
        raise RuntimeError("netlab executable not found")
    monkeypatch.setattr(images, "run_netlab", boom)
    images._netlab_default_clab_images.cache_clear()
    try:
        assert images._netlab_default_clab_images() == {}
        # extra-repo aliases still resolve from docker alone
        _local(monkeypatch, {"vrnetlab/cisco_n9kv": {"9.3.9"}})
        assert images.device_image_map() == {"nxos": "vrnetlab/cisco_n9kv:9.3.9"}
    finally:
        images._netlab_default_clab_images.cache_clear()
