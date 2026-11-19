import csol
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel


def test_package_and_sdk_imports():
    """The installed package and chosen SDK v1 interfaces import offline."""
    assert csol.__name__ == "csol"
    assert all(
        callable(interface)
        for interface in (ClientSession, streamablehttp_client, FastMCP, BaseModel)
    )
