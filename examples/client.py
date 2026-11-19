"""Run with `uv run python examples/client.py` after starting the server."""

import asyncio
import sys

from mcp import Client


async def main(url: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        print("Tools:", [tool.name for tool in tools.tools])

        if not tools.tools:
            print("Connected successfully. No tools are registered yet.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"))
