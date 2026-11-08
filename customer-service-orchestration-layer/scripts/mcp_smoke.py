"""Exercise a live CSOL endpoint using the pinned official MCP client."""

import argparse
import asyncio
import json
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from csol.auth import load_bearer_token
from csol.models import TurnResponse


async def smoke(url: str, token: str) -> None:
    # A fresh synthetic reference keeps repeat smoke runs independent of saved workflows.
    session_ref = f"demo-smoke-{uuid.uuid4().hex}"
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=10) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
    ):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            print(f"initialize: OK (server={initialized.serverInfo.name})")
            listed = await session.list_tools()
            names = sorted(tool.name for tool in listed.tools)
            if names != ["csol_process_turn"] or listed.nextCursor is not None:
                raise RuntimeError(f"Unexpected tool discovery: {names}")
            print(f"tools/list: OK ({', '.join(names)})")
            result = await session.call_tool(
                "csol_process_turn",
                {"session_ref": session_ref, "message_id": "smoke-001", "message": "hello"},
            )
            response = TurnResponse.model_validate(result.structuredContent)
            if (
                result.isError
                or response.session_ref != session_ref
                or response.mode != "demo"
                or response.state != "IDLE"
                or response.state_version != 0
                or response.allowed_actions != ["buy_package", "send_credit"]
                or response.error_code is not None
            ):
                raise RuntimeError("Unexpected tools/call response")
            print("tools/call: OK")
            print(json.dumps(result.structuredContent, indent=2))
            print("MCP smoke: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    args = parser.parse_args()
    try:
        token = load_bearer_token()
    except ValueError as error:
        parser.error(str(error))
    asyncio.run(smoke(args.url, token))


if __name__ == "__main__":
    main()
