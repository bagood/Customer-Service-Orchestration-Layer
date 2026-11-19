"""Run with `uv run python examples/client.py` after starting the server."""

import asyncio
import sys

from mcp import Client


async def main(url: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        print("Tools:", [tool.name for tool in tools.tools])

        result = await client.call_tool("add", {"a": 2, "b": 3})
        if result.is_error:
            raise RuntimeError(result.content)
        print("Addition:", result.structured_content)

        resource = await client.read_resource("template://info")
        print("Resource:", resource.contents)

        prompt = await client.get_prompt("summarize", {"text": "MCP connects AI apps to tools."})
        print("Prompt:", prompt.messages)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"))
