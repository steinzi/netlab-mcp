"""Unit tests for harvest: stage/rollup logic + results.yaml ingest into the matrix."""
from conftest import FIXTURES
from netlab_mcp.store import harvest, matrix


def test_stage_mapping():
    assert harvest._stage(True) == "pass"
    assert harvest._stage(False) == "fail"
    assert harvest._stage({"warning": ["x"]}) == "warning"
    assert harvest._stage(None) is None
    assert harvest._stage("weird") is None


def test_rollup_logic():
    assert harvest._rollup({"a": None, "b": None}) == "partial"
    assert harvest._rollup({"stage_validate": "pass", "x": "fail"}) == "fail"
    assert harvest._rollup({"stage_validate": None, "stage_up": "pass"}) == "partial"
    assert harvest._rollup({"stage_validate": "warning", "stage_up": "pass"}) == "warning"
    assert harvest._rollup({"stage_validate": "pass", "stage_up": "pass"}) == "pass"


def test_harvest_results_ingests():
    out = harvest.harvest_results(
        str(FIXTURES / "results_sample.yaml"), module="harvestunit", dut_platform="frr"
    )
    assert out["ok"] and out["ingested"] == 3  # the non-dict entry is skipped
    verdicts = {
        r["scenario"]: r["verdict"]
        for r in matrix.query(module="harvestunit", dut_platform="frr")
    }
    assert verdicts.get("ebgp-test") == "pass"
    assert verdicts.get("warn-test") == "warning"
    assert verdicts.get("fail-test") == "fail"


def test_harvest_missing_file():
    out = harvest.harvest_results("/no/such/file.yaml", module="x", dut_platform="y")
    assert out["ok"] is False and out["ingested"] == 0
