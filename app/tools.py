"""Example tools. Register your application's tool handlers here."""

from typing import Annotated

from mcp.server import MCPServer
from pydantic import BaseModel, Field


class AdditionResult(BaseModel):
    total: int


class GreetingResult(BaseModel):
    message: str


def register_tools(server: MCPServer) -> None:
    @server.tool()
    async def add(a: int, b: int) -> AdditionResult:
        """Add two integers and return their total."""
        return AdditionResult(total=a + b)

    @server.tool()
    async def greet(
        name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")],
    ) -> GreetingResult:
        """Return a greeting for a name containing at least one non-whitespace character."""
        return GreetingResult(message=f"Hello, {name.strip()}!")
