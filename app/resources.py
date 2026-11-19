"""Example read-only context exposed to MCP clients."""

import json

from mcp.server import MCPServer

from app import __version__


def register_resources(server: MCPServer) -> None:
    @server.resource("template://info", mime_type="application/json")
    async def template_info() -> str:
        """Describe this template and its available examples."""
        return json.dumps(
            {
                "name": server.name,
                "version": __version__,
                "description": "A starter MCP server hosted by FastAPI.",
                "tools": ["add", "greet"],
            }
        )
