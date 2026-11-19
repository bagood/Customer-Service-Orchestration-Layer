# Python + FastAPI MCP template

A small, runnable Model Context Protocol server using the official Python MCP SDK
and FastAPI. It provides Streamable HTTP at `/mcp`, typed example tools, a resource,
a reusable prompt, a health endpoint, and tests through a real MCP client.

This is a reusable starter. The existing CSOL design documents remain reference
material; their workflows, persistence, and Hermes integration are not implemented here.

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --python 3.12
cp .env.example .env
uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Or use pip with Python 3.11+:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

| URL | Purpose |
| --- | --- |
| `http://127.0.0.1:8000/mcp` | MCP Streamable HTTP endpoint |
| `http://127.0.0.1:8000/healthz` | Health check returning `{"status":"ok"}` |
| `http://127.0.0.1:8000/docs` | Swagger UI for the FastAPI service routes |

MCP tools use the MCP protocol and are discovered by an MCP client. They are not
individual REST endpoints and do not appear in Swagger UI. No model API key is
needed to start the server or call the examples.

## Try the MCP client

With the server running, open another terminal:

```bash
uv run python examples/client.py
```

The example discovers tools, calls `add` with `2` and `3` (returning `{"total":5}`),
reads the resource, and retrieves the prompt. Pass a different endpoint as its first
argument if needed.

For an interactive client:

```bash
npx @modelcontextprotocol/inspector
```

Select **Streamable HTTP**, enter `http://127.0.0.1:8000/mcp`, and connect.
For other MCP hosts, select their HTTP transport and use the same URL.

| Capability | Name | Example input |
| --- | --- | --- |
| Tool | `add` | `{"a":2,"b":3}` |
| Tool | `greet` | `{"name":"Ada"}` |
| Resource | `template://info` | Read the URI |
| Prompt | `summarize` | `{"text":"Text to summarize"}` |

The prompt returns instructions for the client's model; the server does not
generate a summary itself. Tool type hints and Pydantic models define the input
and output schemas. Invalid tool input produces an MCP tool error.

## Project layout

```text
app/
  main.py         # FastAPI factory, routes, mount, and MCP lifespan
  config.py       # MCP_* environment settings
  mcp_server.py   # MCP server construction and capability registration
  tools.py        # Typed tool examples
  resources.py    # Read-only resource example
  prompts.py      # Reusable prompt example
examples/
  client.py       # Official SDK HTTP client
tests/
  conftest.py     # Live HTTP server fixture on an ephemeral port
  test_server.py  # Discovery, calls, validation, resource/prompt, HTTP checks
```

Add tools in `app/tools.py` with `@server.tool()` inside `register_tools`. Keep
business logic in separate service modules as your application grows. Add resources
and prompts in their corresponding registration functions.

FastAPI owns the MCP session manager's lifespan because mounted applications do
not start their own lifespan automatically. The root mount is deliberately last,
and the SDK supplies `/mcp`, avoiding an accidental `/mcp/mcp` endpoint.
The transport is stateless and returns JSON responses; tools can still use a
database when your application needs persisted state.

## Configuration

Copy `.env.example` to `.env`. Settings use the `MCP_` prefix:

| Variable | Purpose |
| --- | --- |
| `MCP_SERVER_NAME` | Name advertised to MCP clients |
| `MCP_ALLOWED_HOSTS` | JSON array of permitted MCP Host headers |
| `MCP_ALLOWED_ORIGINS` | JSON array of permitted MCP Origin headers |
| `MCP_PORT` | Docker Compose host port (default `8000`; container port stays `8000`) |

Defaults permit loopback hosts and loopback HTTP origins. For a reverse proxy or
Docker service DNS name, add its hostname (for example, `"mcp:8000"`) to the Host
allowlist and the actual client origin if it sends an Origin header. Host and
Origin checks are transport protections, not authentication. This starter has no
authentication; add authorization before exposing private tools remotely.
Browser applications also need explicit CORS configuration on the FastAPI app.

## Tests and lint

```bash
uv sync --python 3.12
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests start the actual FastAPI app on a loopback port and use the official SDK
client. They cover automatic and legacy client negotiation, discovery, structured
tool results, invalid arguments, unknown tools, resources, prompts, transport
Host/Origin rejection, and FastAPI routes.

## Deploy with Docker Compose

Requires Docker Engine/Desktop and Docker Compose v2. From the project directory:

```bash
docker compose up --build --wait
```

Compose builds the image, starts the `mcp` service in the background, and waits for
its health check to pass. Connect your MCP client to
`http://127.0.0.1:8000/mcp`; health and Swagger UI are available at `/healthz` and
`/docs`. The service restarts unless explicitly stopped and runs as the non-root
user defined by the Dockerfile.

Configuration has defaults, so `.env` is optional. To customize it, copy
`.env.example` to `.env` and edit the values before starting. Compose automatically
reads `.env` and passes the server settings into the container. Set `MCP_PORT` to
change the published host port, for example:

```bash
MCP_PORT=8080 docker compose up --build --wait
```

Then connect to `http://127.0.0.1:8080/mcp`. The published port binds to the host's
loopback interface. Other services in the same Compose project can use
`http://mcp:8000/mcp`; the Compose defaults and `.env.example` include `mcp:8000` in
the MCP Host allowlist. If overriding that list, retain the service hostname for
container-to-container access.

```bash
docker compose ps             # Service and health status
docker compose logs -f mcp    # Follow server logs
docker compose down           # Stop and remove the deployment
```

After changing settings or source code, rerun `docker compose up --build --wait`.
The service is stateless and needs no persistent volume in this template.

### Build and run without Compose

```bash
docker build -t python-fastapi-mcp .
docker run --rm -p 127.0.0.1:8000:8000 python-fastapi-mcp
```

The image runs as a non-root user and checks `/healthz`. The command publishes the
service on the host's loopback interface. To customize settings, pass
`--env-file .env` before the image name. The image build uses the dependency ranges
in `pyproject.toml`; local uv development uses `uv.lock` for repeatable installs.

## References

- [Official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
- [Mounting MCP in an ASGI application](https://py.sdk.modelcontextprotocol.io/run/asgi/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Docker Compose service reference](https://docs.docker.com/reference/compose-file/services/)
