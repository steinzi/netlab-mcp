"""Unit tests for lab capability probes (docker/containerlab mocked)."""
import types

import netlab_mcp.engine.probes as probes


def _which(present):
    return lambda name: ("/usr/bin/" + name) if name in present else None


def _rc(code):
    return lambda *a, **k: types.SimpleNamespace(returncode=code)


def test_docker_ok_true(monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", _which({"docker"}))
    monkeypatch.setattr(probes.subprocess, "run", _rc(0))
    assert probes.docker_ok() is True


def test_docker_ok_missing_binary(monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", _which(set()))
    assert probes.docker_ok() is False


def test_docker_ok_daemon_down(monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", _which({"docker"}))
    monkeypatch.setattr(probes.subprocess, "run", _rc(1))
    assert probes.docker_ok() is False


def test_cmd_ok_swallows_exception(monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", _which({"docker"}))

    def boom(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(probes.subprocess, "run", boom)
    assert probes.docker_ok() is False


def test_lab_available_all_present(monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", _which({"docker", "containerlab"}))
    monkeypatch.setattr(probes.subprocess, "run", _rc(0))
    r = probes.lab_available()
    assert r["ok"] and r["docker"] and r["containerlab"] and r["reasons"] == []


def test_lab_available_none_present(monkeypatch):
    monkeypatch.setattr(probes.shutil, "which", _which(set()))
    r = probes.lab_available()
    assert not r["ok"] and not r["docker"] and not r["containerlab"]
    assert len(r["reasons"]) == 2
