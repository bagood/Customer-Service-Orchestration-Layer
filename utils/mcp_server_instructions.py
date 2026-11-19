"""Load the MCP server's Markdown instructions from the application package."""

from importlib.resources import files
from pathlib import Path


def load_mcp_server_instructions(path: str | Path | None = None) -> str:
    """Read UTF-8 MCP server instructions, rejecting missing or empty files.

    Default to app/mcp_server.md independently of the working directory, including
    in installed packages. An explicit path can override the default file.
    """
    instructions_path = files("app").joinpath("mcp_server.md") if path is None else Path(path)
    instructions = instructions_path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise ValueError(f"MCP server instructions must not be empty: {instructions_path}")
    return instructions
