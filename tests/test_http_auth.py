"""HTTP transport + bearer auth: token sources, 401 enforcement, /health bypass."""
import asyncio

import httpx
import pytest

import netlab_mcp.server as s

_INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "t", "version": "0"}},
}
_HDR = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def test_auth_from_env_token(monkeypatch):
    monkeypatch.setenv("NETLAB_MCP_TOKEN", "sekrit")
    monkeypatch.delenv("NETLAB_MCP_TOKEN_FILE", raising=False)
    assert s._auth_from_env() is not None


def test_auth_from_env_token_file(monkeypatch, tmp_path):
    f = tmp_path / "token"
    f.write_text("sekrit\n")
    monkeypatch.delenv("NETLAB_MCP_TOKEN", raising=False)
    monkeypatch.setenv("NETLAB_MCP_TOKEN_FILE", str(f))
    assert s._auth_from_env() is not None


def test_auth_from_env_absent(monkeypatch):
    monkeypatch.delenv("NETLAB_MCP_TOKEN", raising=False)
    monkeypatch.delenv("NETLAB_MCP_TOKEN_FILE", raising=False)
    assert s._auth_from_env() is None


def test_http_auth_enforced_but_health_open(monkeypatch):
    """Bearer-gated /mcp with an open /health on the SAME app — the deployment shape."""
    monkeypatch.setenv("NETLAB_MCP_TOKEN", "sekrit")
    from fastmcp import FastMCP

    m = FastMCP("auth-test", auth=s._auth_from_env())

    @m.custom_route("/health", methods=["GET"])
    async def health(req):
        from starlette.responses import JSONResponse
        return JSONResponse({"ok": True})

    async def go():
        app = m.http_app()
        async with app.router.lifespan_context(app):
            t = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=t, base_url="http://t") as c:
                assert (await c.get("/health")).status_code == 200
                assert (await c.post("/mcp", json=_INIT, headers=_HDR)).status_code == 401
                assert (await c.post("/mcp", json=_INIT, headers={
                    **_HDR, "authorization": "Bearer wrong"})).status_code == 401
                assert (await c.post("/mcp", json=_INIT, headers={
                    **_HDR, "authorization": "Bearer sekrit"})).status_code == 200
    asyncio.run(go())


def test_main_refuses_public_bind_without_auth(monkeypatch):
    monkeypatch.setenv("NETLAB_MCP_TRANSPORT", "http")
    monkeypatch.setenv("NETLAB_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("NETLAB_MCP_TOKEN", raising=False)
    monkeypatch.delenv("NETLAB_MCP_TOKEN_FILE", raising=False)
    monkeypatch.setattr(s.mcp, "auth", None, raising=False)
    with pytest.raises(SystemExit, match="without auth"):
        s.main()


def test_main_rejects_unknown_transport(monkeypatch):
    monkeypatch.setenv("NETLAB_MCP_TRANSPORT", "carrier-pigeon")
    with pytest.raises(SystemExit, match="carrier-pigeon"):
        s.main()


def test_auth_from_env_bad_token_file(monkeypatch, tmp_path):
    monkeypatch.delenv("NETLAB_MCP_TOKEN", raising=False)
    monkeypatch.setenv("NETLAB_MCP_TOKEN_FILE", str(tmp_path / "missing"))
    with pytest.raises(SystemExit, match="cannot read NETLAB_MCP_TOKEN_FILE"):
        s._auth_from_env()


def test_main_rejects_non_numeric_port(monkeypatch):
    monkeypatch.setenv("NETLAB_MCP_TRANSPORT", "http")
    monkeypatch.setenv("NETLAB_MCP_PORT", "http")
    with pytest.raises(SystemExit, match="must be a number"):
        s.main()
