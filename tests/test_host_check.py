"""host_check tool + /health route, driven through the in-memory FastMCP client."""
import asyncio

from fastmcp import Client

import netlab_mcp.server as s


def _data(r):
    for attr in ("data", "structured_content"):
        v = getattr(r, attr, None)
        if v is not None:
            return v
    return r


def test_host_check_shape():
    async def go():
        async with Client(s.mcp) as c:
            out = _data(await c.call_tool("host_check", {}))
            assert set(out) >= {"ok", "lab_available", "versions", "allowed_platforms",
                                "installed_device_images", "validation_plugins"}
            assert out["versions"]["netlab"]
            # capability map reflects the installed netlab (26.06 ground truth)
            assert "frr" in out["validation_plugins"]["ospf"]
            assert "srlinux" not in out["validation_plugins"]["ospf"]
            assert "frr" in out["allowed_platforms"]
    _run = asyncio.run(go())


def test_health_route_payload():
    async def go():
        # custom_route handlers are plain ASGI; exercise via the http app in-process.
        import httpx

        app = s.mcp.http_app()
        # lifespan must run so the route table is live
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                r = await c.get("/health")
                assert r.status_code == 200
                body = r.json()
                assert body["ok"] is True
                assert isinstance(body["lab_available"], bool)
                assert body["netlab_version"]
    asyncio.run(go())
