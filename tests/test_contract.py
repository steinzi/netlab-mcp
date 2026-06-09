"""Contract tests — assert the netlab CLI behaviors we depend on, on the pinned version.

These guard against upstream drift (flags / exit codes / output files moving). No docker.
"""
from conftest import FIXTURES
from netlab_mcp.engine.runner import cleanup, netlab_version, new_workdir, run_netlab

MVP = (FIXTURES / "mvp_bgp.yml").read_text()


def test_version_resolves():
    assert netlab_version() != "unknown"


def test_create_emits_clab_yml():
    wd = new_workdir("contract-create-")
    try:
        (wd / "topology.yml").write_text(MVP)
        r = run_netlab(["create", "topology.yml"], cwd=wd)
        assert r.ok, r.stderr
        assert (wd / "clab.yml").is_file()
    finally:
        cleanup(wd)


def test_initial_dash_o_renders_without_docker():
    wd = new_workdir("contract-initial-")
    try:
        (wd / "topology.yml").write_text(MVP)
        assert run_netlab(["create", "topology.yml"], cwd=wd).ok
        r = run_netlab(["initial", "-o", "configs"], cwd=wd)
        assert r.ok, r.stderr
        files = list((wd / "configs").glob("*"))
        # one file per (node, module); srlinux + frr both present
        assert any(f.name.startswith("dut.") for f in files)
        assert any(f.name.startswith("peer.") for f in files)
    finally:
        cleanup(wd)


def test_module_support_yaml_format_supported():
    wd = new_workdir("contract-show-")
    try:
        r = run_netlab(["show", "module-support", "--format", "yaml", "-m", "bgp"], cwd=wd)
        assert r.ok, r.stderr
        assert "srlinux" in r.stdout
    finally:
        cleanup(wd)
