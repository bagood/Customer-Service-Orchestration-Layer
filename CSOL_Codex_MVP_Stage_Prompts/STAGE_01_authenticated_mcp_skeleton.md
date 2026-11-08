# Stage 01 — Authenticated MCP skeleton

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

## Objective
Prove standard MCP connectivity with **one** mutation-capable entrypoint and an optional read-only menu, before implementing business logic.

## Implement
1. Implement Python MCP Streamable HTTP server on port 8000 at `/mcp` with **only** `csol_process_turn(session_ref, message_id, message)` and optional `csol_get_menu()`. There must be no exported purchase, transfer, state-setting or backend tools.
2. Use Pydantic to validate tool inputs and outputs; forbid unexpected fields and bound string lengths (e.g. message ≤ 1000 characters, identifiers ≤ 128). Response fields: `session_ref`, `mode`, `state`, `state_version`, `customer_reply`, `allowed_actions`, `transaction`, `simulated`, `safe_to_display`, optional `error_code`. Define consistent error codes for invalid arguments and unavailable server state.
3. Initial `csol_process_turn` returns a safe, fixed two-option demo menu; it does not execute any workflow or transaction.
4. Implement REAL server-side authentication of HTTP MCP requests using a deployment-injected bearer token, with constant-time secret comparison where appropriate. Reject invalid/missing tokens **before** tool discovery or execution. Apply explicit Host and Origin policy that permits the intended Docker service name `csol:8000` and local testing hosts; follow the pinned SDK's actual transport-security API. Do not disable all Host/Origin protection to fix a connectivity issue.
5. Implement `scripts/mcp_smoke.py` with an official MCP client that tests initialize, tools/list, and tools/call against the live endpoint using the token. Provide one command to run the server locally and one to run the smoke test.

## Acceptance gate
- Authorized MCP initialize/list/call works and exposes only approved tools.
- Missing/invalid bearer token is rejected; there is no state mutation.
- Bad Host/Origin, invalid payload sizes and unknown tools are rejected.
- No custom `/chat` or `/v1/chat/completions` API added.

## Stop and report
Show the exact MCP client smoke command and its output. Do not implement routing yet.
