"""Contract checks through the official MCP client and real HTTP transport."""

import json

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
async def test_tool_discovery_and_calls(server_url: str, mode: str) -> None:
    async with Client(f"{server_url}/mcp", mode=mode) as client:
        discovered = await client.list_tools()
        tools = {tool.name: tool for tool in discovered.tools}
        assert set(tools) == {"add", "greet"}
        assert tools["add"].input_schema["required"] == ["a", "b"]
        assert tools["add"].output_schema["properties"]["total"]["type"] == "integer"

        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert not result.is_error
        assert result.structured_content == {"total": 5}

        greeting = await client.call_tool("greet", {"name": "  Ada  "})
        assert not greeting.is_error
        assert greeting.structured_content == {"message": "Hello, Ada!"}


@pytest.mark.anyio
async def test_resources_and_prompts(server_url: str) -> None:
    async with Client(f"{server_url}/mcp") as client:
        resources = await client.list_resources()
        assert "template://info" in {str(resource.uri) for resource in resources.resources}
        resource = await client.read_resource("template://info")
        info = json.loads(resource.contents[0].text)
        assert info["tools"] == ["add", "greet"]

        prompts = await client.list_prompts()
        assert "summarize" in {prompt.name for prompt in prompts.prompts}
        prompt = await client.get_prompt("summarize", {"text": "An example document."})
        assert "An example document." in prompt.messages[0].content.text


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["", "   ", "a" * 101])
async def test_invalid_tool_input(server_url: str, name: str) -> None:
    async with Client(f"{server_url}/mcp") as client:
        result = await client.call_tool("greet", {"name": name})
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
