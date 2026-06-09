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
