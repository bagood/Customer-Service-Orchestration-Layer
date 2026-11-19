"""Contract checks through the official MCP client and real HTTP transport."""

import httpx
import pytest
from mcp import Client


def test_fastapi_routes(server_url: str) -> None:
    with httpx.Client(base_url=server_url, trust_env=False) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/").json()["mcp_endpoint"] == "/mcp"
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "/healthz" in schema["paths"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_landing_capability_discovery(server_url: str, mode: str) -> None:
    async with Client(f"{server_url}/mcp", mode=mode) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == ["classify_intent"]
        assert tools.tools[0].input_schema["required"] == ["session_ref", "message_id", "message"]
        resources = await client.list_resources()
        assert resources.resources == []
        prompts = await client.list_prompts()
        assert prompts.prompts == []


@pytest.mark.anyio
async def test_invalid_landing_input(server_url: str) -> None:
    async with Client(f"{server_url}/mcp") as client:
        result = await client.call_tool(
            "classify_intent", {"session_ref": "s1", "message_id": "m1", "message": "   "}
        )
        assert result.is_error


@pytest.mark.anyio
async def test_unknown_tool(server_url: str) -> None:
    async with Client(f"{server_url}/mcp") as client:
        result = await client.call_tool("does_not_exist", {})
        assert result.is_error


def test_mcp_rejects_untrusted_host_and_origin(server_url: str) -> None:
    headers = {"Accept": "application/json, text/event-stream"}
    with httpx.Client(base_url=server_url, trust_env=False) as client:
        host_response = client.post(
            "/mcp", headers={**headers, "Host": "untrusted.example"}, json={}
        )
        assert host_response.status_code == 421
        origin_response = client.post(
            "/mcp", headers={**headers, "Origin": "https://untrusted.example"}, json={}
        )
        assert origin_response.status_code == 403
