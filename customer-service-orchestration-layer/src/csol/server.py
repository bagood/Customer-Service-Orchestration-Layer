"""Authenticated MCP transport with a SQLite-backed demo purchase controller."""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.routing import Route

from csol.auth import BearerTokenMiddleware, load_bearer_token
from csol.config import DEFAULT_CONFIG_DIR, load_configuration
from csol.controller import Controller
from csol.models import ErrorCode, TurnInput, TurnResponse
from csol.store import DEFAULT_DB_PATH, Store

LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BODY_SIZE = 16 * 1024


def error_response(code: ErrorCode, session_ref: str | None = None) -> TurnResponse:
    replies = {
        "INVALID_ARGUMENTS": "Invalid demo request. No transaction has been executed.",
        "SERVER_UNAVAILABLE": (
            "The demo service is unavailable. The transaction outcome is unconfirmed. "
            "Do not retry automatically."
        ),
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


def create_app(*, db_path: Path | None = None, config_dir: Path = DEFAULT_CONFIG_DIR) -> Starlette:
    # No insecure default: fail before constructing the transport if misconfigured.
    token = load_bearer_token()
    config = load_configuration(config_dir)
    store = Store(
        db_path if db_path is not None else Path(os.environ.get("CSOL_DB_PATH", DEFAULT_DB_PATH))
    )
    controller = Controller(store, config)
    server = Server("csol", version="0.3.0")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="csol_process_turn",
                description=(
                    "Process a synthetic telecom demo turn with deterministic routing and "
                    "persistent state. Package purchases use typed simulation balances, "
                    "exact confirmation and an internal mock transaction. "
                    "Session references do not "
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
            response = TurnResponse.model_validate(controller.process_turn(turn))
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

    app = Starlette(
        routes=[Route("/mcp", endpoint=BearerTokenMiddleware(manager.handle_request, token))],
        lifespan=lifespan,
    )
    app.state.controller = controller
    return app


def main() -> None:
    # One private service worker. Docker networking is configured in a later stage.
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
