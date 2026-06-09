"""Unit tests for matrix artifact cache + (de)serialization helpers."""
import json

from netlab_mcp.store import matrix


def test_slug_sanitizes():
    assert matrix._slug("bgp/srlinux frr@26.06") == "bgp-srlinux-frr-26.06"
    assert matrix._slug("///") == "run"


def test_cache_artifacts_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix, "ARTIFACTS_DIR", tmp_path / "art")
    topo, cfg = matrix.cache_artifacts(
        "bgp-srlinux-frr-26.06", "module: [bgp]\n", {"dut": {"bgp": "router bgp 65000"}}
    )
    assert matrix._load_text(topo) == "module: [bgp]\n"
    assert matrix._load_json(cfg) == {"dut": {"bgp": "router bgp 65000"}}


def test_load_helpers_missing_and_corrupt(tmp_path):
    assert matrix._load_text(None) is None
    assert matrix._load_text(str(tmp_path / "nope.txt")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert matrix._load_json(str(bad)) is None


def test_norm_encodes_lists():
    r = matrix._norm({"module": "bgp", "peer_platforms": ["frr", "eos"], "warnings": ["w"]})
    assert r["peer_platforms"] == json.dumps(["eos", "frr"])  # sorted
    assert r["warnings"] == json.dumps(["w"])
    assert r["scenario"] == "" and r["provider"] == "clab" and r["ts"]


def test_decode_parses_json_cols():
    d = matrix._decode({"peer_platforms": '["frr"]', "warnings": "[]", "module": "bgp"})
    assert d["peer_platforms"] == ["frr"] and d["warnings"] == []
