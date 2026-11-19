"""Construct an independent MCP server for each FastAPI application instance."""

from mcp.server import MCPServer

from app import __version__
from app.config import Settings
from utils.instructions import load_instructions


def create_mcp_server(settings: Settings) -> MCPServer:
    server = MCPServer(
        name="customer-service-orchestration-layer",
        version=__version__,
        description=(
            "Customer Service Orchestration Layer (CSOL). "
            "Manages supported customer-service workflows, validates "
            "requests, enforces business policies, and returns approved "
            "outcomes and customer-facing responses."
        ),
        instructions=load_instructions(),
    )
    return server
