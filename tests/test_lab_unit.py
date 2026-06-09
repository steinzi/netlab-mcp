"""Unit tests for lab.validate_in_lab verdict logic — no docker; seams stubbed.

The real lab path is exercised by the docker-gated tests/test_lab.py and the
lab-validate.yml workflow; here we isolate the verdict-mapping + false-pass guard.
"""
import netlab_mcp.engine.lab as lab
from netlab_mcp.engine.runner import RunResult


def _stub(monkeypatch, *, up_rc=0, validate):
    """Stub every external seam of validate_in_lab so it runs offline."""
    monkeypatch.setattr(lab, "lab_available",
                        lambda: {"ok": True, "docker": True, "containerlab": True, "reasons": []})
    monkeypatch.setattr(lab, "resolved_node_devices",
                        lambda *a, **k: {"ok": True,
                                         "node_device": {"dut": "srlinux", "peer": "frr"},
                                         "errors": []})
    monkeypatch.setattr(lab, "resolved_tools",
                        lambda *a, **k: {"ok": True, "tools": [], "errors": []})
    monkeypatch.setattr(lab, "_parse_configs", lambda *a, **k: {})
    monkeypatch.setattr(lab, "_read", lambda *a, **k: None)

    def fake_run(args, cwd, timeout=120, env_extra=None):
        if args[0] == "up":
            return RunResult(["netlab", *args], up_rc,
                             "" if up_rc == 0 else "Fatal error in netlab: deploy boom", "")
        if args[0] == "validate":
            return validate
        return RunResult(["netlab", *args], 0, "", "")

    monkeypatch.setattr(lab, "run_netlab", fake_run)


def test_skipped_validation_demoted_to_no_tests(monkeypatch):
    vr = RunResult(["netlab", "validate"], 0,
                   "[SKIPPED] no plugin\n[SUCCESS] Tests passed: 0\n"
                   "One test out of 0 were skipped, the results are not reliable\n", "")
    _stub(monkeypatch, validate=vr)
    out = lab.validate_in_lab("x", ["srlinux", "frr"], module="bgp", scenario="unit-notests")
    assert out["verdict"] == "no_tests" and out["ok"] is False


def test_real_pass(monkeypatch):
    vr = RunResult(["netlab", "validate"], 0, "[PASS] ok\n[SUCCESS] Tests passed: 1\n", "")
    _stub(monkeypatch, validate=vr)
    out = lab.validate_in_lab("x", ["srlinux", "frr"], module="bgp", scenario="unit-pass")
    assert out["verdict"] == "pass" and out["ok"] is True


def test_deploy_failed_recorded(monkeypatch):
    _stub(monkeypatch, up_rc=1, validate=RunResult(["netlab", "validate"], 0, "", ""))
    out = lab.validate_in_lab("x", ["srlinux", "frr"], module="bgp", scenario="unit-deployfail")
    assert out["verdict"] == "deploy_failed" and out["ok"] is False
    assert out["errors"]


def test_validate_timeout_verdict(monkeypatch):
    vr = RunResult(["netlab", "validate"], 124, "", "[timeout after 600s]")
    _stub(monkeypatch, validate=vr)
    out = lab.validate_in_lab("x", ["srlinux", "frr"], module="bgp", scenario="unit-timeout")
    assert out["verdict"] == "timeout"
