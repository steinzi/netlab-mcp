"""Live lab test — requires docker + containerlab. Skipped automatically when absent."""
import pytest

from conftest import FIXTURES
from netlab_mcp.engine import lab
from netlab_mcp.engine.probes import lab_available
from netlab_mcp.store import matrix

MVP = (FIXTURES / "mvp_bgp.yml").read_text()

pytestmark = pytest.mark.docker


@pytest.mark.skipif(not lab_available()["ok"], reason="docker + containerlab not available")
def test_mvp_bgp_passes_in_lab():
    out = lab.validate_in_lab(MVP, ["srlinux", "frr"], module="bgp", scenario="mvp-ebgp")
    assert out["verdict"] in ("pass", "warning"), out
    assert out["rendered_config"].get("dut")
    # verdict persisted + served back as known-good
    good = matrix.get_known_good("bgp", "srlinux")
    assert good and good["verdict"] in ("pass", "warning")
    assert good["topology_yaml"] and good["config"]


def test_validate_in_lab_degrades_cleanly_without_lab():
    """Even with the marker, the unavailable path must be safe to call anywhere."""
    if lab_available()["ok"]:
        pytest.skip("lab is available; this checks the no-lab fallback")
    out = lab.validate_in_lab(MVP, ["srlinux", "frr"])
    assert out["verdict"] == "unavailable"
    assert out["ok"] is False
