"""Deployment token validation and authentication before MCP dispatch."""

import hmac
import logging
import os
import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOGGER = logging.getLogger(__name__)


def load_bearer_token() -> str:
    token = os.environ.get("CSOL_BEARER_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_~-]{32,512}", token):
        raise ValueError(
            "SERVER_UNAVAILABLE: CSOL_BEARER_TOKEN must be injected as "
            "32-512 URL-safe characters (letters, digits, _, ~, or -)"
        )
    return token


class BearerTokenMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        values = Headers(scope=scope).getlist("authorization")
        scheme, _, candidate = values[0].partition(" ") if len(values) == 1 else ("", "", "")
        matches = hmac.compare_digest(candidate.encode("latin-1"), self.token)
        if scheme.lower() != "bearer" or not matches:
            LOGGER.warning("MCP request rejected; code=UNAUTHORIZED")
            response = JSONResponse(
                {"error_code": "UNAUTHORIZED"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="csol"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
