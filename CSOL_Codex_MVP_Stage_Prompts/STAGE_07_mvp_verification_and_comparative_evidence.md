# Stage 07 — MVP verification and comparative evidence

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

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
