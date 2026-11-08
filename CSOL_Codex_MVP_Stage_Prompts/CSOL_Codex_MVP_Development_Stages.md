# CSOL MCP MVP — Sequential Development Stages for Codex

**Source documents:** `CSOL_Components_Architecture_MCP_Revised(1).pdf` and `CSOL_Development_Plan_MCP_Revised(1).html` (8 November 2026). This guide simplifies those documents into one-stage-at-a-time implementation instructions; it is **not** a production specification.

## What this MVP is proving

A separate, small Python CSOL can deterministically route the supported telecom intents, enforce legal state transitions, validate customer-entered simulation data, authorize mock purchase/credit actions once, preserve progress after restart and return canonical customer-safe replies via standard MCP. It is **not** claiming authenticated customer identity, real balance verification or mandatory model tool-use / final-output approval.

### Intended architecture

`Customer → Hermes channel/gateway → Hermes MCP client → authenticated private /mcp → CSOL router + FSM + SQLite → private mock telecom functions → canonical MCP result → Hermes reply (demo)`.

### Two workflows (keep exact demo semantics)

- `buy_package`: A Rp 10,000 / B Rp 20,000 → amount typed as demo balance → exact confirmation → controller-only mock purchase → feedback (1–5 or skip) → IDLE.
- `send_credit`: Indonesian synthetic MSISDN → positive whole IDR amount → typed balance ≥ amount → exact confirmation → controller-only mock transfer → feedback → IDLE.

### Minimal public tool contract

- `csol_process_turn(session_ref, message_id, message)` — sole mutation-capable MCP tool.
- Optional `csol_get_menu()` — read-only and anonymous.
- **Never** register `mock_buy_package`, `mock_send_credit`, `set_state` or arbitrary backend tools.

Illustrative result fields (version/contract must be tested against the pinned SDK):

```json
{
  "session_ref": "demo-session-001",
  "mode": "buy_package",
  "state": "SELECT_PACKAGE",
  "state_version": 1,
  "customer_reply": "Silakan pilih Paket A Rp 10.000 atau Paket B Rp 20.000.",
  "allowed_actions": ["select_package"],
  "transaction": null,
  "simulated": true,
  "safe_to_display": true
}
```

`allowed_actions` is metadata, NOT permission to mutate. A service bearer token authenticates Hermes, NOT an individual customer. All sessions, MSISDNs, balances and ledger entries are synthetic.

## Recommended execution order

| Stage | Codex development chunk | Proof before advancing |
|---|---|---|
| 00 | Repository and test foundation | Imports and pytest run |
| 01 | Authenticated MCP skeleton | Authorized initialize/list/call, rejection tests |
| 02 | Router and SQLite | Bilingual intent route, persistent session, cancel |
| 03 | Package purchase FSM | B + insufficient balance retry + exact confirm |
| 04 | Credit transfer FSM and feedback | Transfer validation and return-to-IDLE |
| 05 | Safety and reliability | Zero skipped/duplicate mock transactions; UNKNOWN safe |
| 06 | Docker + existing Hermes | Private discovery, real MCP tool call, SQLite trace |
| 07 | Evaluation and decision | 15+ synthetic cases, bypass and fidelity evidence |

**Codex usage:** start a Codex session at the new CSOL repository root. Supply the global contract and only **one** stage file. Ask it to stop after implementation, tests and a report. Review and commit the stage before sending the next one. These stage files are also bundled individually in a ZIP archive.

## Pragmatic MVP design choices (intentional simplifications)

1. Use **one** Streamable HTTP MCP entrypoint rather than an agent planner with many tools.
2. Define just **two** deterministic FSM workflows; plain Python functions enforce steps even when YAML lists them.
3. Keep **one** SQLite file and **one** Python MCP server process. Persist sessions, transactions, processed message IDs, feedback and audit.
4. Use **one** service bearer token, Docker bridge and explicit Host/Origin policy; real end-user binding is deferred.
5. Use **fixed demo catalog**, customer-entered balance, synthetic MSISDN and deterministic mock outcomes; no real charging, provisioning or user records.
6. Handle ambiguous/multiple requests by **asking which one first**, not a multi-intent agent planner.
7. Treat explicit confirmation and backend status as prerequisites for approved success templates. No LLM for numeric validation or success wording.
8. Reuse existing Hermes container/channel when possible. Add only persisted MCP configuration and profile instructions, not Hermes source patches.

## Definition of done: credible MVP, NOT production-ready

- Hermes discovers and invokes CSOL over authenticated MCP; CSOL's port is private.
- Both simulated customer flows complete, invalid inputs retry, optional feedback resets to IDLE.
- All transaction paths require CSOL-owned prerequisites and exact customer confirmation.
- **0 unauthorized mock transactions** and **0 duplicate mock transactions** across all deterministic tests.
- SQLite restart/resume, failure/UNKNOWN and injected instructions are exercised.
- Tool-call coverage and Hermes reply fidelity are **measured and reported**, not presumed to be 100%.
- The report **explicitly flags** no mandatory MCP invocation, no trusted end-customer identity, and no trusted outbound final-message gate. Do not use this MVP with real balances or credit.

## Stage prompts

Each section below can be copied into Codex. If using an individual stage file, its global contract is already included.

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

---

## Stage 00 — Repository and test foundation

## Objective
Create a tiny independent Python project that Codex can build incrementally. Do **not** implement live MCP connections or financial workflows in this stage.

## Implement
1. Create `customer-service-orchestration-layer/` with `src/csol/__init__.py`, `tests/`, `configs/`, `hermes/`, `scripts/`, `data/`, `.gitignore`, `.env.example`, `requirements.txt`, `README.md` and `pytest.ini` (or equivalent). Avoid generating dozens of empty modules.
2. In README describe the precise message flow: customer → Hermes channel → Hermes MCP client → CSOL MCP server → private mock gateway + SQLite → canonical reply → Hermes channel.
3. Document non-goals and two hard limits: model-mediated MCP calls are not mandatory, and final Hermes text cannot be forcibly approved without a separate outbound gate.
4. Choose and pin a tested version of Python 3.11+ and a compatible MCP Python SDK/pytest/Pydantic/PyYAML stack. Record pinned versions and the command used to verify imports. Do not blindly assume snippets for a different SDK major version work.
5. Add one smoke test asserting package import and one minimal configuration parsing test. All persistent/generated secrets and SQLite files must be gitignored.

## Acceptance gate
- `python -m pytest -q` passes from repository root.
- `python -c "import csol"` works after the documented install/setup.
- No credentials, real service access or modifications to Hermes source.
- README contains one honest MVP success criterion and one explicit production safety disclaimer.

## Stop and report
List created paths, pinned dependencies and test outputs. Do not start Stage 01.

---

## Stage 01 — Authenticated MCP skeleton

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

---

## Stage 02 — Deterministic router and SQLite state

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

---

## Stage 03 — Package purchase FSM

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

---

## Stage 04 — Credit transfer FSM, feedback, reset

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

---

## Stage 05 — Reliability, authorization and adversarial hardening

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

---

## Stage 06 — Private Docker and real Hermes MCP integration

## Objective
Connect the already-working CSOL server to the **existing** Hermes installation without patching Hermes source or creating a redundant Hermes deployment.

## Implement
1. Add a lean `Dockerfile` and `compose.yaml` for **CSOL only** by default; run a single Python server process and bind-mount `./data` for SQLite. Use a named internal/private Docker bridge network, with DNS alias/service `csol`, and **no published host port** for 8000 (Docker `expose` is okay).
2. Ensure the deployed Hermes gateway container can reach `http://csol:8000/mcp` over that bridge. If Hermes already has its own Compose project, provide a short **network attach** procedure or a small documented Compose overlay rather than replacing the working stack. Hermes retains whatever egress network it needs for its model provider and customer channel.
3. Provide `hermes/mcp-config.example.yaml` for `mcp_servers.csol` pointing at the private URL; whitelist `csol_process_turn` and optionally `csol_get_menu`; set `supports_parallel_tool_calls: false` and sensible connect/tool timeouts. Disable MCP resources/prompts unless used. Add an Authorization header with a securely supplied token; the installed Hermes version's environment interpolation should be explicitly verified. **Merge** settings into its persisted `/opt/data/config.yaml` rather than overwriting existing model/channel credentials.
4. Provide a short Hermes customer-service profile that asks Hermes to call `csol_process_turn` before each substantial reply and reproduce its canonical `customer_reply`; label this as **instruction, not enforcement**. Do not give Hermes direct telecom credentials; restrict unnecessary native tools for the test profile.
5. Run Docker compose and an authenticated MCP client smoke test **inside an authorized container on the private network**. Then test at least one Package B path using the already-configured Hermes CLI/chat/channel. Verify actual discovery/tool names; check gateway logs for calls and confirm the corresponding SQLite rows.
6. Record compatibility of the pinned Hermes release with the pinned MCP SDK and any required config/reload behavior. Do not open `/mcp` publicly just to make a test client work.

## Acceptance gate
- `docker compose up -d --build` starts CSOL with SQLite data persistent.
- Network checks prove MCP is reachable by Hermes and **not** published to the host.
- Hermes discovers approved tools and successfully executes a demo turn via the MCP protocol.
- Container restart preserves active workflow state.
- If Hermes omits a call, record that as an observable model bypass; never invent a success test.

## Stop and report
Include commands, actual connection/config path, tool discovery names, and one customer-to-ledger trace. Do not start evaluation stage.

---

## Stage 07 — MVP verification and comparative evidence

## Objective
Produce convincing, reproducible **evidence**, not a feature-rich platform. Show what the independent CSOL does and does not enforce.

## Implement
1. Create a single simple evaluation script plus a CSV/JSON file of **at least 15** synthetic tests: two happy paths; package C; Package B balance 15000 → 25000; equal balance; no confirmation; malformed MSISDN; zero/negative amount; bad transfer balance; injected fake developer message; forged tool result; duplicate message; parallel confirm; failed/UNKNOWN mock; restart/resume; feedback/reset. Use existing pytest tests where possible instead of rewriting an elaborate framework.
2. For each scenario capture: expected state/transaction; actual state/transaction; pass/fail; simulated transaction count; reason/error code; MCP-call count and latency where measurable. Redact recipient data.
3. Conduct a small Hermes end-to-end study through a real configured chat/channel: verify whether Hermes called `csol_process_turn` on each turn and whether its final visible reply matches the approved `customer_reply`. If stable upstream message IDs or transcript correlation are unavailable, mark coverage as `not measurable`, not 100%.
4. Include **two critical bypass cases**: Hermes replies without an MCP call; Hermes claims success despite a failed/UNKNOWN CSOL result. These do not change CSOL ledger, but reveal that customer-visible response enforcement is **not provided by MCP**. Mark full production safety as blocked without a trusted channel identity and outbound approval gate.
5. If a comparable Hermes-only baseline can be executed with the same model, scenarios, mock semantics and tool access, compare workflow conformance, unauthorized/duplicate mock mutations, p50/p95 end-to-end latency, MCP call coverage, final reply fidelity and (where accessible) tokens. Otherwise say `baseline not measured`; don't fabricate gains.
6. Write `MVP_REPORT.md` with a short architecture, exact tests/commands, a table of pass/fail metrics, one Package B transcript, evidence of hard action enforcement, observed tool-bypass limitations, and a prioritized go/no-go decision for **next research step**, not production.

## Acceptance gate
- All deterministic workflow and adversarial unit tests pass, with **zero unauthorized** and **zero duplicate** mock transaction executions.
- Results include actual MCP discovery/call evidence and one Hermes chat trace, or explicitly disclose blockers.
- Report distinguishes (a) CSOL action safety proven in tests from (b) unproven full customer-response safety.
- All deliverables remain small, runnable and reusable when upgrading Hermes.

## Stop and report
Summarize quantitative results and recommend one focused follow-up: outbound identity/reply gate, broader adversarial scenarios, or controlled comparison. No production integrations.

---

## Sources and compatibility verification

Grounded in the two uploaded 8 Nov 2026 MCP-revised CSOL documents. Their core responsibilities and two telecom workflows are preserved; the eight-stage split and simplification choices are **implementation recommendations**.

Check the exact pinned installed versions before writing transport/authentication code or changing Hermes configuration:

- Hermes MCP user guide: https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp
- Hermes MCP config reference: https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference
- MCP Python SDK: https://py.sdk.modelcontextprotocol.io/
- MCP SDK transport/deployment and Host allowlist: https://py.sdk.modelcontextprotocol.io/run/deploy/

The current Hermes config reference describes environment-variable substitution in HTTP MCP `headers`, but verify it for the pinned runtime and never commit bearer secrets. SDK interfaces differ across major releases; adapt code to the actual tested SDK rather than copying illustrative snippets blindly.
