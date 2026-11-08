# Stage 06 — Private Docker and real Hermes MCP integration

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

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
