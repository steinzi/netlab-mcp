"""Unit tests for transform._json_after_banner (parses JSON after netlab's [INFO] banner)."""
from netlab_mcp.engine.transform import _json_after_banner


def test_parses_json_after_info_banner():
    out = '[INFO] Using lab topology file topology.yml\n{"dut": {"device": "srlinux"}}'
    assert _json_after_banner(out) == {"dut": {"device": "srlinux"}}


def test_parses_json_with_no_banner():
    assert _json_after_banner('{"a": 1}') == {"a": 1}


def test_malformed_json_returns_none():
    assert _json_after_banner("[INFO] junk\n{not valid json") is None


def test_no_brace_returns_none():
    assert _json_after_banner("no json here") is None


def test_empty_returns_none():
    assert _json_after_banner("") is None
