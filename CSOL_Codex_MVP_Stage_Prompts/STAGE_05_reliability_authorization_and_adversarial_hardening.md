# Stage 05 — Reliability, authorization and adversarial hardening

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

## Objective
Prove that manipulated inputs, retries, race conditions and uncertain mock results cannot bypass **CSOL action controls**. Do not attempt to make model output itself a hard security boundary.

## Implement
1. Apply fail-closed state/action checks and recheck saved prerequisites immediately before executing each private mock operation. Never authorize based on model-provided `state`, `allowed_actions` or instruction text.
2. Enforce `(session_ref, message_id)` uniqueness in SQLite. For a repeat, return the previously recorded response without applying a second state change. For a repeated confirmed operation, use the same persisted transaction idempotency key and transaction result. Do not derive safety solely from Hermes-supplied message IDs; synthetic IDs are test data.
3. Serialize same-session mutations with short SQLite write transactions (`BEGIN IMMEDIATE` or equivalent), version checks and a UNIQUE idempotency key. Test two parallel confirmations against one persisted session. Exactly one transaction row may reach `SUCCEEDED`.
4. Model transaction statuses `PENDING / SUCCEEDED / FAILED / UNKNOWN`. Include a deterministic test-only switch in the private mock to simulate failure and unknown/timeout. When `UNKNOWN`, **never** display success or blindly re-invoke the financial mock; mark the workflow as pending/manual-review for the demo.
5. Tighten contracts: reject overly long text, unexpected fields, invalid state/version, malformed numbers and suspicious requests **through normal state validation**, not a giant regex blacklist for prompt injections. Keep approved replies deterministic; log error codes and state transitions with redacted values.
6. Add adversarial tests with English/Indonesian fake authority (`I'm the developer`, `abaikan instruksi`), fake tool output, attempts to skip confirmation, cross-session guesses, duplicated calls and repeated session messages. The shared bearer token authenticates the **Hermes service**, not the customer; for cross-session test, show the absence of trusted customer binding explicitly rather than claiming production isolation.
7. Keep retry and input limits small; avoid distributed locks, queues, real-money reconciliation, DLP platforms or complex security products.

## Acceptance gate
- Unauthorized executed mock transactions = **0** in tests.
- Duplicate executed mock transactions = **0** in tests.
- Invalid token/arguments and state-jump injections mutate no state or ledger.
- Unknown/timeout never results in a success claim, and is not blindly retried.
- State survives restart; all original happy-path tests still pass.

## Stop and report
Produce a short safety checklist with proof from exact test names. List unimplemented production controls separately, especially identity binding and outbound reply gating.
