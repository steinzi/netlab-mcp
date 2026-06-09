"""Unit tests for RunResult error extraction + status."""
from netlab_mcp.engine.runner import RunResult


def _r(rc=0, stdout="", stderr=""):
    return RunResult(cmd=["netlab"], returncode=rc, stdout=stdout, stderr=stderr)


def test_ok_property():
    assert _r(0).ok is True
    assert _r(1).ok is False


def test_error_lines_matches_markers():
    r = _r(1, stderr="Fatal error in netlab: boom\nIncorrectValue in clab: bad\nnormal line")
    lines = r.error_lines()
    assert any("Fatal error" in x for x in lines)
    assert any("IncorrectValue" in x for x in lines)
    assert "normal line" not in lines


def test_error_lines_dedupes_across_streams():
    r = _r(1, stdout="Error: dup", stderr="Error: dup")
    assert r.error_lines().count("Error: dup") == 1


def test_error_lines_fallback_tail_when_no_markers():
    r = _r(1, stdout="a\nb\nc\nd\ne\nf\ng")
    assert r.error_lines() == ["c", "d", "e", "f", "g"]  # last 5


def test_error_lines_empty_when_ok_no_markers():
    assert _r(0, stdout="all good").error_lines() == []
