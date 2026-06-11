"""Test setup: make src importable and redirect store/work dirs to a temp location.

Env must be set before netlab_mcp.config is imported (it binds paths at import time), so this
runs at conftest import — before any test module imports the package.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_TMP = Path(tempfile.mkdtemp(prefix="nlmcp-test-"))
os.environ.setdefault("NETLAB_MCP_STORE", str(_TMP / "store"))
os.environ.setdefault("NETLAB_MCP_WORKDIR", str(_TMP / "work"))

FIXTURES = ROOT / "tests" / "fixtures"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_local_docker_images(monkeypatch):
    """Keep unit tests independent of the host's docker store.

    Image pinning reads `docker images`; without this, generated-topology assertions
    would change shape depending on what happens to be loaded on the dev box. Tests
    that exercise the image path monkeypatch the boundary themselves (test_images.py).
    """
    from netlab_mcp.engine import images

    monkeypatch.setattr(images, "installed_images", lambda refresh=False: {})
