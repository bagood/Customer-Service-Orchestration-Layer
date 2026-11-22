import json
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
import jwt
from fastapi import FastAPI, Header, HTTPException
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from redis.asyncio import Redis
from starlette.applications import Starlette
from starlette.routing import Route

from app.database import Accounts
from app.engine import Engine, allowed, catalog
from app.model import Input
from app.store import BindingMismatch, Conversations

logger = logging.getLogger(__name__)
ERRORS = {
    "invalid_input", "stale_revision", "out_of_step", "return_pending", "no_pending_return",
    "operation_pending", "revision_conflict", "account_missing", "balance_limit", "await_fresh_confirmation",
}


@asynccontextmanager
async def services():
    key = os.environ["CSOL_BINDING_KEY"]
    if len(key.encode()) < 32:
        raise ValueError("CSOL_BINDING_KEY requires at least 32 bytes")
    async with Redis.from_url(os.environ["REDIS_URL"], decode_responses=True) as redis:
        await redis.ping()
        async with asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=8) as pool:
            yield Engine(Conversations(redis), Accounts(pool)), key


def identity(token, key):
    claims = jwt.decode(token, key, algorithms=["HS256"], audience="csol",
                        options={"require": ["exp", "sub", "customer", "turn"]})
    session, customer, turn = claims["sub"], claims["customer"], claims["turn"]
    if not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (session, customer, turn)):
        raise jwt.InvalidTokenError("Invalid identity")
    return session, customer, turn


def tool_result(data, error=False):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(data))], structuredContent=data, isError=error,
    )


def create_app(open_services=services):
    server = Server("csol")
    manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)

    @asynccontextmanager
    async def lifespan(application):
        async with open_services() as (engine, key), manager.run():
            application.state.engine = engine
            application.state.key = key
            yield

    application = FastAPI(lifespan=lifespan)

    @server.list_tools()
    async def list_tools():
        result = []
        for name, description, schema in catalog():
            params = schema.model_json_schema()
            params["properties"]["binding"] = {"type": "string", "description": "Supplied by the channel adapter."}
            params.setdefault("required", []).append("binding")
            result.append(types.Tool(name=name, description=description, inputSchema=params,
                                     annotations=types.ToolAnnotations(readOnlyHint=schema is Input)))
        return result

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        arguments = dict(arguments)
        try:
            session, customer, turn = identity(arguments.pop("binding", ""), application.state.key)
            result = await application.state.engine.invoke(session, customer, name, arguments, turn=turn)
        except (jwt.PyJWTError, BindingMismatch):
            return tool_result({"outcome": "invalid_binding"}, True)
        except Exception as exc:
            # Connection failures can happen on either side of a commit.
            # Avoid exposing DSNs, identity tokens, or customer data in errors.
            logger.error("CSOL invocation failed (%s)", type(exc).__name__)
            return tool_result({"outcome": "service_unavailable",
                                "instruction": "Read the current instruction and reconcile any pending action."}, True)
        return tool_result(result, result["outcome"] in ERRORS)

    @application.get("/scope")
    async def scope(authorization: str = Header(default="")):
        try:
            token = authorization.removeprefix("Bearer ")
            session, customer, _ = identity(token, application.state.key)
            c = await application.state.engine.conversations.read(session, customer)
        except (jwt.PyJWTError, BindingMismatch):
            raise HTTPException(403, "Invalid conversation binding") from None
        return {"allowed_tools": allowed(c), "state": c.state, "step": c.step, "revision": c.revision}

    application.mount("/", Starlette(routes=[
        Route("/mcp", endpoint=manager.asgi_app, methods=["GET", "POST", "DELETE"]),
    ]))
    return application


app = create_app()
