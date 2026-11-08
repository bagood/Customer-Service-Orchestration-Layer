# Stage 04 — Credit transfer FSM, feedback, reset

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

## Objective
Add the second workflow and finish the customer feedback loop with the same simple controller patterns.

## Implement
1. Implement `ENTER_MSISDN → ENTER_AMOUNT → ENTER_BALANCE → CONFIRM_TRANSFER → [internal EXECUTE_TRANSFER] → FEEDBACK` for `send_credit`. Internal execution is not a public MCP operation.
2. Normalize the documented Indonesian demo formats `08...`, `628...`, `+628...` into one canonical `628...` value. For MVP, document one illustrative rule, e.g. mobile format `08` followed by 8–11 digits. Reject malformed inputs; these are **synthetic** test numbers, not proof of ownership.
3. Require transfer amount to be a positive ASCII integer; customer-typed balance must be a nonnegative ASCII integer and ≥ amount. Reject amount 0, negative, decimals, free text and insufficient balance without leaving the current collection state.
4. At confirmation, show the amount and a suitably masked recipient; only exact `yes`/`ya` invokes private `mock_send_credit` after rechecking state and prerequisites. Only recorded `SUCCEEDED` mock outcomes get a demo-success reply.
5. Implement shared `FEEDBACK`: accept `1`–`5` or `skip` / `lewati`. Persist feedback or skipped status, clear active workflow to `IDLE`, preserve audit/transactions, and show main menu. Cancel before execution returns to menu without a transaction.
6. Reuse the existing response contract, store and validators. Avoid adding a generic workflow execution language or extra abstraction layers.

## Acceptance gate
- All three supported MSISDN prefixes normalize correctly; malformed numbers are rejected.
- 0/negative/decimal transfer amount or insufficient balance causes 0 transfers.
- Valid recipient + amount 20000 + balance 20000 + exact yes produces one `SUCCEEDED` simulated transfer.
- Rating and skip both reset to `IDLE`; next turn routes as new intent while audit history remains.
- Tests for Package B still pass.

## Stop and report
Provide both workflow traces, changed files and all test outputs. Do not begin hardening yet.
