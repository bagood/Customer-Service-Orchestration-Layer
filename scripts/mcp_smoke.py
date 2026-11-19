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


async def smoke(
    url: str, token: str, scenario: str = "menu", session_ref: str | None = None,
) -> None:
    # A fresh synthetic reference keeps repeat smoke runs independent of saved workflows.
    session_ref = session_ref or f"demo-smoke-{uuid.uuid4().hex}"
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
            journeys = {
                "menu": [("smoke-001", "hello", "IDLE", 0)],
                "package-b-start": [
                    ("b-01", "buy package", "SELECT_PACKAGE", 1),
                    ("b-02", "B", "ENTER_BALANCE", 2),
                    ("b-03", "20000", "CONFIRM_PURCHASE", 3),
                ],
                "package-b-finish": [
                    # Replay across container restart must retain the original response.
                    ("b-03", "20000", "CONFIRM_PURCHASE", 3),
                    ("b-04", "yes", "FEEDBACK", 5),
                    ("b-05", "skip", "IDLE", 6),
                ],
            }
            for message_id, message, state, version in journeys[scenario]:
                result = await session.call_tool(
                    "csol_process_turn",
                    {"session_ref": session_ref, "message_id": message_id, "message": message},
                )
                response = TurnResponse.model_validate(result.structuredContent)
                if (
                    result.isError or response.error_code is not None
                    or response.session_ref != session_ref
                    or (response.state, response.state_version) != (state, version)
                ):
                    raise RuntimeError("Unexpected tools/call response")
                if state == "FEEDBACK":
                    if response.transaction is None or response.transaction.status != "SUCCEEDED":
                        raise RuntimeError("Missing successful demo receipt")
                elif response.transaction is not None:
                    raise RuntimeError("Unexpected transaction receipt")
                if state == "IDLE" and (
                    response.mode != "demo"
                    or response.allowed_actions != ["buy_package", "send_credit"]
                ):
                    raise RuntimeError("Unexpected menu response")
                print("tools/call: OK")
                print(json.dumps(result.structuredContent, indent=2))
            print("MCP smoke: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument(
        "--scenario", choices=["menu", "package-b-start", "package-b-finish"], default="menu",
    )
    parser.add_argument("--session-ref", help="Synthetic reference shared across the restart check")
    args = parser.parse_args()
    if args.scenario != "menu" and not args.session_ref:
        parser.error("Package B restart checks require --session-ref")
    try:
        token = load_bearer_token()
    except ValueError as error:
        parser.error(str(error))
    asyncio.run(smoke(args.url, token, args.scenario, args.session_ref))


if __name__ == "__main__":
    main()
