"""Run the actual ASGI application on an ephemeral local port for MCP tests."""

import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def server_url() -> Iterator[str]:
    app = create_app(Settings(_env_file=None))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(base_url=base_url, trust_env=False, timeout=1) as client:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if not thread.is_alive():
                        pytest.fail("Test server exited during startup")
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    pytest.fail("Test server did not become healthy within 10 seconds")
            yield base_url
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                pytest.fail("Test server did not shut down cleanly")
