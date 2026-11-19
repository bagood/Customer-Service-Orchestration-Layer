# Python + FastAPI MCP template

A small, runnable Model Context Protocol server using the official Python MCP SDK
and FastAPI. It provides Streamable HTTP at `/mcp`, Markdown server instructions,
a health endpoint, and a landing-workflow intent classification tool. The external
decision model uses a configurable OpenAI-compatible Chat Completions API.

The landing workflow identifies `buy_package` and `send_credit`, asks for
clarification when needed, and records validated intent state. Purchase and
credit-transfer execution, durable persistence, customer authentication, and a
Hermes runtime integration are not implemented.

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
needed to start the server or run the example client.

## Try the MCP client

With the server running, open another terminal:

```bash
uv run python examples/client.py
```

The example connects to the MCP server and lists `classify_intent`. Pass a
different endpoint as its first argument if needed. Classification requires the
provider settings described below; discovery and health checks do not.

For an interactive client:

```bash
npx @modelcontextprotocol/inspector
```

Select **Streamable HTTP**, enter `http://127.0.0.1:8000/mcp`, and connect.
For other MCP hosts, select their HTTP transport and use the same URL.

## Project layout

```text
app/
  main.py         # FastAPI factory, routes, mount, and MCP lifespan
  config.py       # MCP_* environment settings
  mcp_server.py   # MCP server construction and instructions
  mcp_server.md   # Server instructions loaded at startup
examples/
  client.py       # Official SDK HTTP client
utils/
  mcp_server_instructions.py # MCP server instruction loader
workflow-config/landing/
  finite-state.py # Intent enum and immutable, validated Pydantic state
  instructions.md # Landing workflow instructions for the MCP client
  tools.yaml     # Exposed tool name and description
workflow-tools/landing/
  intent_classifier.py # MCP handler, session coordination, and retry cache
  helper/
    decision_model.py # OpenAI-compatible HTTP client and validated decisions
    update_intent_fsm.py # Allowed state transitions
  instructions/
    intent_classification.md # System instructions sent to the decision model
tests/
  conftest.py     # Live HTTP server fixture on an ephemeral port
  test_server.py  # MCP discovery, input validation, and HTTP checks
  test_landing.py # State invariants, concurrency, and retry behavior
  test_landing_simulation.py # Real HTTP calls to the local provider stand-in
```

The MCP server loads the landing tool implementation and reads `tools.yaml` to
register its public tool. The workflow Markdown is appended to the server's
instructions. Your hyphenated directory names are preserved: Python loads these
packages, including `finite-state.py`, through `importlib`.

Edit `app/mcp_server.md` to change the instructions sent to MCP clients.
`utils.mcp_server_instructions.load_mcp_server_instructions()` loads this packaged
file; pass a path to override it. Missing or empty files fail startup explicitly.
The server loads this file at startup, so restart the server after editing it
(or rebuild with `docker compose up --build --wait`). The file is included in
Docker images and installed Python packages. It documents the intended CSOL
workflow contract while identifying which capabilities are currently implemented.

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
| `MCP_LLM_BASE_URL` | Provider's API base URL, including `/v1` when required |
| `MCP_LLM_MODEL` | Provider-specific model identifier |
| `MCP_LLM_API_KEY` | Bearer credential; optional for providers that require no authentication |
| `MCP_LLM_TIMEOUT_SECONDS` | HTTP timeout in seconds (default `20`) |
| `MCP_LLM_RESPONSE_FORMAT` | `json_object` (default) or `json_schema` |

Configure your chosen provider in the ignored `.env` file:

```dotenv
MCP_LLM_BASE_URL=https://your-provider.example/v1
MCP_LLM_MODEL=your-model-name
MCP_LLM_API_KEY=your-api-key
```

The adapter posts to `<base-url>/chat/completions`. Choose a model that supports
JSON output. Use `MCP_LLM_RESPONSE_FORMAT=json_schema` if it also supports strict
JSON Schema responses. Both modes are validated locally against the same schema;
unknown intents, extra fields, inconsistent decisions, refusals, and truncated or
malformed responses are rejected. Provider errors are sanitized and leave state
unchanged. No provider request is made until the classifier is called. The caller's
original message and the previous unresolved message are sent to the configured
provider. Classification accuracy and resistance to misleading text must be
evaluated with the chosen live model; schema validation only constrains structure.

## Landing workflow

Call the MCP tool with:

```json
{
  "session_ref": "demo-session-1",
  "message_id": "message-1",
  "message": "Saya mau beli paket internet"
}
```

Its input is the customer message, not a model-supplied intent or desired state.
The response includes `status`, `state`, `next_workflow`, `next_step`, and
`customer_reply`. Unclear/unsupported requests return `needs_clarification` and
`ask_customer`. A recognized intent returns `classified` and `handoff_pending`.
No package is purchased and no credit is transferred by this tool.

Each successful classification increments the session's state version. Identical
retries using the same session and message identifier return their original result
without another model call. Reusing a message identifier for changed text is an
error. Per-session locks serialize concurrent calls; once classified, a new
message cannot reclassify the session. Failed provider calls do not consume the
identifier, so an unchanged retry can succeed later.

State is in memory and limited to 1,000 sessions and 32 successful landing messages
per session. It is isolated per application instance and cleared on restart. Run a
single worker until state and idempotency are moved to shared durable storage.
Session references are demo correlation identifiers, not authenticated identities.

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
client. They cover automatic and legacy client negotiation, landing discovery,
input validation, unknown tools, transport Host/Origin rejection, and FastAPI
routes. State tests cover invariant checks, transitions, concurrent retries, and
failure recovery without invoking a live model.

Run the optional provider integration suite against the committed Postman
simulation (requires a Postman CLI with `simulation` support):

```bash
# Terminal 1: serves a synthetic Chat Completions provider locally.
postman simulation run postman/simulations/landing.sim.yaml --port 4517 --no-history

# Terminal 2: makes real HTTP requests to that stand-in.
MCP_TEST_PROVIDER_URL=http://127.0.0.1:4517/llm/v1 uv run pytest -q
```

Without `MCP_TEST_PROVIDER_URL`, provider simulation tests are skipped. The fixture
responses exercise supported intents, ambiguity and clarification context, both
JSON modes, HTTP 429/500, timeouts, refusals, and malformed/invalid completions.
They establish transport and state behavior against a stand-in, not live model
accuracy. No real provider credentials are used. The simulation context records
the provider assumptions that remain unverified.

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
The HTTP transport is stateless; landing sessions live in the server process and
are lost when its container restarts. No persistent volume is used in this template.

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
