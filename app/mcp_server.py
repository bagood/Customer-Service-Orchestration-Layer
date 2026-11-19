"""Construct an independent MCP server for each FastAPI application instance."""

from importlib import import_module

from mcp.server import MCPServer

from app import __version__
from app.config import Settings
from utils.mcp_server_instructions import load_mcp_server_instructions


def create_mcp_server(settings: Settings) -> MCPServer:
    # importlib preserves the user's hyphenated workflow directory names.
    landing = import_module("workflow-tools.landing.intent_classifier")
    server = MCPServer(
        name="customer-service-orchestration-layer",
        version=__version__,
        description=(
            "Customer Service Orchestration Layer (CSOL). "
            "Manages supported customer-service workflows, validates "
            "requests, enforces business policies, and returns approved "
            "outcomes and customer-facing responses."
        ),
        instructions=(
            load_mcp_server_instructions() + "\n\n" + landing.load_landing_instructions()
        ),
    )
    landing.register_landing_tools(server, settings)
    return server
