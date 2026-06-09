"""Unit tests for topo.devices_in_doc (informational raw-YAML device scan)."""
from netlab_mcp.engine.topo import devices_in_doc


def test_flat_nodes():
    doc = {"nodes": {"a": {"device": "srlinux"}, "b": {"device": "frr"}}}
    assert devices_in_doc(doc) == {"srlinux", "frr"}


def test_nested_groups_and_defaults():
    doc = {"groups": {"g": {"device": "eos"}}, "defaults": {"device": "vyos"}}
    assert devices_in_doc(doc) == {"eos", "vyos"}


def test_lists_and_missing_device():
    doc = {"nodes": [{"device": "frr"}, {"name": "x"}], "links": ["a-b"]}
    assert devices_in_doc(doc) == {"frr"}


def test_non_string_device_ignored():
    doc = {"device": 123, "nodes": {"a": {"device": "srlinux"}}}
    assert devices_in_doc(doc) == {"srlinux"}


def test_empty_or_none():
    assert devices_in_doc({}) == set()
    assert devices_in_doc(None) == set()
