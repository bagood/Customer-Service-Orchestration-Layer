"""Load Markdown instructions from the source tree or an installed package."""

from pathlib import Path


def load_instructions(path: str | Path | None = None) -> str:
    """Read UTF-8 instructions, rejecting missing or empty files.

    Without a path, load the server's default Markdown file independently of the
    working directory. An explicit path can be used for other instruction files.
    """
    if path is None:
        root = Path(__file__).resolve().parent.parent
        instructions_path = root / "instructions" / "mcp_server.md"
        if not instructions_path.is_file():
            # Wheels bundle the same Markdown file inside the application package.
            instructions_path = root / "app" / "instructions" / "mcp_server.md"
    else:
        instructions_path = Path(path)

    instructions = instructions_path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise ValueError(f"Instructions must not be empty: {instructions_path}")
    return instructions
