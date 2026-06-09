"""Unit tests for config: EULA gating, truthy parsing, netlab binary discovery."""
import netlab_mcp.config as config
from netlab_mcp.config import _truthy, allowed_platforms, check_platforms


def test_truthy_values():
    for v in ("1", "true", "TRUE", "yes", "on", " Yes "):
        assert _truthy(v) is True
    for v in ("0", "false", "no", "off", "", None, "maybe"):
        assert _truthy(v) is False


def test_ceos_eula_gating(monkeypatch):
    monkeypatch.delenv("NETLAB_MCP_ACCEPT_CEOS_EULA", raising=False)
    ok, rejected, _ = check_platforms(["ceos"])
    assert not ok and "ceos" in rejected
    assert "ceos" not in allowed_platforms()

    monkeypatch.setenv("NETLAB_MCP_ACCEPT_CEOS_EULA", "1")
    ok, rejected, _ = check_platforms(["ceos"])
    assert ok and not rejected
    assert "ceos" in allowed_platforms()


def test_free_allowed_licensed_rejected():
    ok, rejected, _ = check_platforms(["srlinux", "frr"])
    assert ok and not rejected
    ok, rejected, reason = check_platforms(["srlinux", "nxos", "iosxr"])
    assert not ok
    assert set(rejected) == {"nxos", "iosxr"}
    assert "nxos" in reason


def test_empty_platforms_is_ok():
    ok, rejected, _ = check_platforms([])
    assert ok and not rejected


def test_netlab_bin_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "netlab"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("NETLAB_MCP_NETLAB_BIN", str(fake))
    config.netlab_bin.cache_clear()
    try:
        assert config.netlab_bin() == str(fake)
    finally:
        config.netlab_bin.cache_clear()
