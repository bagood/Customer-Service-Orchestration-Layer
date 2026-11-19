"""Construct an independent MCP server for each FastAPI application instance."""

from mcp.server import MCPServer

from app import __version__
from app.config import Settings
from app.prompts import register_prompts
from app.resources import register_resources
from app.tools import register_tools


def create_mcp_server(settings: Settings) -> MCPServer:
    server = MCPServer(
        settings.server_name,
        version=__version__,
        instructions="Example server with add/greet tools, template info, and a summarize prompt.",
    )
    register_tools(server)
    register_resources(server)
    register_prompts(server)
    return server
