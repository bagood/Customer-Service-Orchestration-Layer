import time
from contextlib import asynccontextmanager

import httpx
import jwt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.main import create_app


async def test_scoped_calls_on_a_stable_http_catalog(engine):
    key = "fixture-signing-key-" * 2

    def binding(session="one", account="test", secret=key):
        return jwt.encode({"aud": "csol", "sub": session, "customer": account, "turn": "1",
                           "exp": int(time.time()) + 60}, secret, algorithm="HS256")

    @asynccontextmanager
    async def connections():
        yield engine, key

    app = create_app(connections)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as http, streamable_http_client("http://localhost/mcp", http_client=http) as (read, write, _):
        async with ClientSession(read, write) as mcp:
            await mcp.initialize()
            initial = await mcp.list_tools()
            assert len(initial.tools) == 14
            assert (await http.get("/scope")).status_code == 403
            args = {"binding": binding()}
            first = await mcp.call_tool("identification_instruction", args)
            assert not first.isError and first.structuredContent["revision"] == 0
            assert (await mcp.call_tool("record_name", {"binding": binding(secret="x" * 32),
                                                        "name": "Ari", "revision": 0})).isError
            engine.accounts.post.return_value = {"outcome": "name_recorded"}
            result = await mcp.call_tool("record_name", {**args, "name": "Ari", "revision": 0})
            assert not result.isError and result.structuredContent["step"] == "intent_classification"
            assert (await mcp.list_tools()).tools == initial.tools
            old = await mcp.call_tool("record_name", {**args, "name": "Old", "revision": 0})
            assert old.isError and old.structuredContent["instruction"]["action"] == "select_service"
            stale = await mcp.call_tool("select_service", {**args, "service": "buy_credits", "revision": 0})
            assert stale.isError and stale.structuredContent["outcome"] == "stale_revision"
            assert (await mcp.call_tool("menu_instruction", {"binding": binding(account="another")})).isError
            assert not (await mcp.call_tool("identification_instruction", {"binding": binding("two")})).isError
