"""FastAPI entry point: uvicorn app.main:create_app --factory --reload."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from app import __version__
from app.config import Settings
from app.mcp_server import create_mcp_server


class HealthResponse(BaseModel):
    status: str = "ok"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    server = create_mcp_server(settings)
    mcp_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=settings.allowed_origins,
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Mounted sub-app lifespans are not run automatically by FastAPI.
        async with server.session_manager.run():
            yield

    app = FastAPI(title=settings.server_name, version=__version__, lifespan=lifespan)
    app.state.mcp = server

    @app.get("/", tags=["service"])
    async def index() -> dict[str, str]:
        return {"name": settings.server_name, "mcp_endpoint": "/mcp", "docs": "/docs"}

    @app.get("/healthz", response_model=HealthResponse, tags=["service"])
    async def health() -> HealthResponse:
        return HealthResponse()

    # Keep this last: the root mount would otherwise swallow FastAPI routes.
    # The child app already defines /mcp; mounting at /mcp would double that path.
    app.mount("/", mcp_app)
    return app
