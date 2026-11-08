# Customer Service Orchestration Layer (CSOL)

CSOL is an independent Python MCP server for a simulated telecom customer-service
assistant. Hermes Agent is the MCP client. The private Streamable HTTP endpoint
is `/mcp` on port 8000.

**Stage 01 status:** authenticated MCP connectivity, strict input/output validation,
and a fixed two-option demo menu. Every valid turn returns that menu. There is
no router, workflow, state machine, database, transaction gateway, Docker setup,
or deployed Hermes connection yet.

## Setup

Run these commands from `customer-service-orchestration-layer/` using CPython
**3.12.13**, recorded in `.python-version`:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m pip check
python -m pytest -q
```

Package metadata permits Python 3.11+, but 3.12.13 is the tested interpreter.
`requirements.txt` supplies the direct dependency pins to `pyproject.toml`:

| Dependency | Pin | Purpose |
| --- | --- | --- |
| Official MCP Python SDK | 1.30.0 | Streamable HTTP server and client |
| Pydantic | 2.14.3 | Strict tool input/output models |
| PyYAML | 6.0.3 | Existing offline configuration sample |
| pytest | 9.2.0 | Automated verification |
| Starlette | 1.10.0 | ASGI application and test client |
| Uvicorn | 0.54.0 | HTTP server |
| HTTPX | 0.28.1 | Official MCP client's HTTP transport |

The build backend remains pinned to setuptools 78.1.1. Transitive dependencies
are resolved by pip; this stage has no complete transitive lockfile.

## Run the server and live smoke test

Inject a secret token into the server environment. It must contain 32–512
characters from `A-Z`, `a-z`, `0-9`, `_`, `~`, and `-`. Generate a value once:

```sh
export CSOL_BEARER_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Start the server in that shell:

```sh
.venv/bin/python -m csol.server
```

In a second shell with **the same token injected**, run the official MCP client:

```sh
.venv/bin/python scripts/mcp_smoke.py --url http://127.0.0.1:8000/mcp
```

The script initializes MCP, verifies that discovery exposes exactly
`csol_process_turn`, calls it, validates the structured response, and prints
`MCP smoke: PASS`. It exits nonzero on failure. The token is read from the
environment, never a command-line argument. `.env.example` documents the
variable; `.env` is not loaded automatically. Keep actual secrets out of Git.
Missing or malformed server configuration prevents startup.

The server binds `0.0.0.0:8000` for the intended private service network. Run it
on a trusted local/private network; container networking is a later stage.
It uses one worker, disables proxy-header trust, and does not configure TLS.

## Tool contract

Only one MCP tool is registered:

```text
csol_process_turn(session_ref, message_id, message)
```

All three arguments must be strings containing at least one non-whitespace
character. Identifiers are limited to 128 characters and `message` to 1000.
Unexpected fields are rejected, including supplied state, permissions, and
transaction data. The MCP discovery schemas are generated from the same
Pydantic models used for validation.

A valid turn returns:

```json
{
  "session_ref": "demo-smoke",
  "mode": "demo",
  "state": "MENU",
  "state_version": 0,
  "customer_reply": "Telecom demo menu (simulation only):\n1. Buy a package (buy_package)\n2. Send credit (send_credit)\nWorkflows are not available yet. No transaction has been executed.",
  "allowed_actions": ["buy_package", "send_credit"],
  "transaction": null,
  "simulated": true,
  "safe_to_display": true
}
```

`allowed_actions` names the two planned demo options; neither is executable in
this stage. It does not grant authorization. The transport is stateless and
does not persist session references or messages. There are no exported purchase,
transfer, state-setting, or backend tools, and no `/chat` or
`/v1/chat/completions` API.

Tool errors have MCP `isError: true` and the same validated response fields,
with `mode: "error"`, `state: "UNAVAILABLE"`, no actions or transaction, a fixed
safe reply, and one of these `error_code` values:

| Code | Meaning |
| --- | --- |
| `INVALID_ARGUMENTS` | Missing, extra, wrong-type, empty, or oversized tool fields; `session_ref` is null |
| `SERVER_UNAVAILABLE` | Internal handler failure or invalid output; validated session reference is preserved |
| `UNKNOWN_TOOL` | Unregistered tool name; `session_ref` is null |

Failure responses do not expose exception details. Output models forbid extra
fields, bound strings, and constrain this stage to version zero, simulation,
safe-display flags, and a null transaction. No state or transaction is created
on valid, invalid, or unauthenticated turns.

## HTTP security policy

Every HTTP request to `/mcp` requires `Authorization: Bearer <token>`.
Authentication uses constant-time secret comparison and runs before request
body parsing, MCP initialization, discovery, or tool execution. Missing,
incorrect, malformed, and duplicate authorization headers receive HTTP 401
with `error_code: "UNAUTHORIZED"` and a Bearer challenge. Query parameters
cannot supply credentials. This is service-to-service authentication, not
end-user identity or OAuth.

The [pinned SDK's transport-security API](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/transport_security.py)
keeps DNS rebinding protection
enabled with exact allowlists:

| Header | Allowed values |
| --- | --- |
| Host | `csol:8000`, `127.0.0.1:8000`, `localhost:8000`, `[::1]:8000` |
| Origin, when present | `http://csol:8000`, `http://127.0.0.1:8000`, `http://localhost:8000`, `http://[::1]:8000` |

Native MCP clients may omit Origin. An invalid Host receives 421; an invalid
Origin receives 403. Other ports and arbitrary origins are rejected. The SDK
also enforces a 16 KiB request-body limit (413), including streamed bodies
without a Content-Length header. Malformed JSON and incorrect Content-Type
are rejected. Unknown paths return 404.

## Verification and limits

```sh
.venv/bin/python -m pytest -q
```

The suite includes the two unchanged Stage 00 tests and tests the real ASGI
application with the official MCP client, authentication, discovery, strict
schemas, safe errors, Host/Origin rejection, payload limits, and fixed menu
behavior. It runs offline and does not require a token in your shell.
The original `configs/example.yaml` remains a Stage 00 offline fixture.
See [Stage 01 verification](docs/stage_01_verification.md) for observed commands
and full live smoke output.

Stage 01 does not establish workflow success, durable session isolation,
idempotency, Docker connectivity, or real Hermes integration. Later stages own
those requirements. CSOL never calls Hermes `/v1/chat/completions` or modifies
Hermes source; later integration adds only a configuration snippet/profile in
this repository for the deployed Hermes persistent configuration.

The eventual MVP remains limited to simulated `buy_package` and `send_credit`
workflows with a deterministic router, controller-owned FSM, SQLite, private
mock transactions, and safe reply templates. No live balance, credit movement,
customer PII, real telecom APIs, RAG, LLM classification, dynamic plugins,
message brokers, PostgreSQL, multi-worker scaling, or separate gateway.

Synthetic session IDs do not authenticate customers. Only controller code may
change state or permit actions. Future transactions require exact, explicit
confirmation and a recorded `SUCCEEDED` result before success wording; unknown
or timed-out outcomes must not trigger blind retries. These are later-stage
requirements. MCP cannot force Hermes to call a tool or display its approved
reply, and returned action lists and tool hints are not authorization.
Potentially destructive Hermes built-ins must be restricted in its deployed
customer-service profile. This demo is not ready for real customers or credit.
