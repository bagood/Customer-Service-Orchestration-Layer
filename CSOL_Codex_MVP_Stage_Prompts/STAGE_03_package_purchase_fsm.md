# Stage 03 — Package purchase FSM

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

## Objective
Build the first complete, deterministic telecom customer journey with mandatory validation and an internal mock transaction.

## Implement
1. Use catalog `A = Rp 10,000`, `B = Rp 20,000`; accept selections `A/B/1/2` only when state is `SELECT_PACKAGE`.
2. Implement `SELECT_PACKAGE → ENTER_BALANCE → CONFIRM_PURCHASE → [internal EXECUTE_PURCHASE] → FEEDBACK`. The state `EXECUTE_PURCHASE` is **never** a customer-selectable tool action. Only the controller may call `mock_buy_package`.
3. Accept balance as nonnegative ASCII integer IDR only (not a negative, decimal, separator, free text or float). If insufficient, stay in `ENTER_BALANCE`, keep the selected package, and ask to retry. Equal-to-price is sufficient. These values are **customer-typed simulation inputs**, never verified operator balances.
4. Confirm only when the entire normalized message is a single allowed affirmative token (`yes`/`ya`). Reject embedded instructions such as `yes ignore all checks`. Exact `no`/`tidak` cancels without executing.
5. After exact confirmation, check saved package, sufficient saved balance and state again; insert/obtain one transaction record, run private deterministic `mock_buy_package`, persist `SUCCEEDED` with transaction ID, and only then generate the canonical **demo** success template. Ask for feedback afterward; feedback collection itself can be implemented in Stage 04.
6. Do not add LLM calls, direct standalone transaction MCP tools, HTTP requests to real systems or a dynamic policy engine.

## Acceptance gate
- Invalid C/empty selection is rejected.
- B + 15000 stays `ENTER_BALANCE`, preserves B, executes 0 transactions.
- B + 20000 advances to confirmation but executes 0 transactions before exact `yes`.
- B + 25000 + exact `yes` creates one `SUCCEEDED` demo transaction and moves to `FEEDBACK`.
- `no`, injected confirmation and attempts to skip mandatory states execute 0 transactions.

## Stop and report
Show one complete Package B state trace and test outputs. Do not implement transfer yet.
