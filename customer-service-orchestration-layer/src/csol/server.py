"""Authenticated, stateless MCP Streamable HTTP skeleton; no workflows yet."""

import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.routing import Route

from csol.auth import BearerTokenMiddleware, load_bearer_token
from csol.models import ErrorCode, TurnInput, TurnResponse

LOGGER = logging.getLogger(__name__)
MENU_REPLY = (
    "Telecom demo menu (simulation only):\n"
    "1. Buy a package (buy_package)\n"
    "2. Send credit (send_credit)\n"
    "Workflows are not available yet. No transaction has been executed."
)
MAX_REQUEST_BODY_SIZE = 16 * 1024


def process_turn(turn: TurnInput) -> TurnResponse:
    """Every valid turn returns the same menu without changing any state."""
    return TurnResponse(
        session_ref=turn.session_ref,
        mode="demo",
        state="MENU",
        state_version=0,
        customer_reply=MENU_REPLY,
        allowed_actions=["buy_package", "send_credit"],
        transaction=None,
        simulated=True,
        safe_to_display=True,
    )


def error_response(code: ErrorCode, session_ref: str | None = None) -> TurnResponse:
    replies = {
        "INVALID_ARGUMENTS": "Invalid demo request. No transaction has been executed.",
        "SERVER_UNAVAILABLE": "The demo service is unavailable. No transaction has been executed.",
        "UNKNOWN_TOOL": "This tool is unavailable. No transaction has been executed.",
    }
    return TurnResponse(
        session_ref=session_ref,
        mode="error",
        state="UNAVAILABLE",
        state_version=0,
        customer_reply=replies[code],
        allowed_actions=[],
        transaction=None,
        simulated=True,
        safe_to_display=True,
        error_code=code,
    )


def tool_result(response: TurnResponse) -> CallToolResult:
    payload = response.model_dump(mode="json", exclude_none=False)
    if response.error_code is None:
        payload.pop("error_code")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
        isError=response.error_code is not None,
    )


def create_app() -> Starlette:
    # No insecure default: fail before constructing the transport if misconfigured.
    token = load_bearer_token()
    server = Server("csol", version="0.1.0")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="csol_process_turn",
                description=(
                    "Process a synthetic telecom demo turn. Currently returns only a fixed "
                    "menu; no workflows or transactions run. Session references do not "
                    "authenticate customers. Returned actions do not grant authorization."
                ),
                inputSchema=TurnInput.model_json_schema(),
                outputSchema=TurnResponse.model_json_schema(),
                annotations=ToolAnnotations(
                    readOnlyHint=False, destructiveHint=False, openWorldHint=False
                ),
            )
        ]

    # Pydantic performs strict validation here, including extra="forbid". This
    # replaces the SDK's generic JSON Schema error with our stable error envelope.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> CallToolResult:
        if name != "csol_process_turn":
            return tool_result(error_response("UNKNOWN_TOOL"))
        try:
            turn = TurnInput.model_validate(arguments)
        except ValidationError:
            return tool_result(error_response("INVALID_ARGUMENTS"))
        try:
            response = TurnResponse.model_validate(process_turn(turn))
            return tool_result(response)
        except Exception:
            # Do not disclose or log model/customer input or internal exception text.
            LOGGER.error("MCP tool failed; returning SERVER_UNAVAILABLE")
            return tool_result(error_response("SERVER_UNAVAILABLE", turn.session_ref))

    manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=True,
        max_request_body_size=MAX_REQUEST_BODY_SIZE,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["csol:8000", "127.0.0.1:8000", "localhost:8000", "[::1]:8000"],
            allowed_origins=[
                "http://csol:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8000",
                "http://[::1]:8000",
            ],
        ),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with manager.run():
            yield

    return Starlette(
        routes=[Route("/mcp", endpoint=BearerTokenMiddleware(manager.handle_request, token))],
        lifespan=lifespan,
    )


def main() -> None:
    # One private service worker. Docker networking is configured in a later stage.
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
