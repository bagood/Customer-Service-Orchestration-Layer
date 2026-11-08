# Stage 02 — Deterministic router and SQLite state

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

## Objective
Make CSOL own intent selection and session state without additional LLM calls.

## Implement
1. Add `configs/global.yaml` containing only two route keyword groups, e.g. Indonesian/English `beli paket` / `buy package` and `transfer pulsa` / `send credit`; use exact normalized phrase/word-boundary matching, not unbounded substring heuristics. Unsupported/ambiguous input returns the menu or asks the customer to pick one intent. If both intents match, ask which one to do first; do not attempt parallel work.
2. Create SQLite tables in a small `store.py`: `sessions` (session ID, active workflow, version, state, state_version, data_json, updated_at), `transactions` (idempotency key UNIQUE, status), `processed_messages` (PRIMARY KEY session ID + message ID, response JSON), `feedback` and `audit_events`. Keep it a **single-process demo** using `sqlite3`, transactions and one persistent database file.
3. Implement controller routing for `IDLE` only, with `buy_package → SELECT_PACKAGE`, `send_credit → ENTER_MSISDN`. Once a workflow is active, do not reroute ordinary messages. Implement explicit `cancel` / `batal` as a safe state reset without backend execution.
4. Add versioned workflow YAML definitions in `configs/workflows/` naming states and catalog. Parse/validate them at startup; Python code, not the YAML alone, enforces allowed transitions.
5. Process one turn into a canonical CSOL response including the saved state and state version. Record minimal audit events without raw customer messages, full MSISDN or bearer tokens.

## Acceptance gate
- Indonesian and English routing starts the correct workflow, while ambiguity and unsupported intents cannot trigger transactions.
- Repeated messages in an active workflow are interpreted as responses to the current state, not as global rerouting.
- State persists across a simulated controller restart; `cancel` returns to `IDLE`.
- No mock transaction is implemented or executed in Stage 02.

## Stop and report
Show sample session rows and four routing tests. Do not build the purchase FSM yet.
