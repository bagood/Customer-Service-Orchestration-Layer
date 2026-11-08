# Stage 00 — Repository and test foundation

# Codex operating contract — applies to EVERY stage

You are implementing the **CSOL MCP MVP** as an independent Python repository. Hermes Agent is the MCP **client**. CSOL is the MCP **server** at the private Streamable HTTP endpoint `/mcp`. Never call Hermes `/v1/chat/completions` from CSOL; never modify Hermes source code. Only add a Hermes configuration snippet/profile in this repository, later merged into the deployed Hermes persistent configuration.

**Hard scope:** two simulated telecom workflows (`buy_package`, `send_credit`), a deterministic router, controller-owned FSM, SQLite, safe reply templates, basic transport authentication and MCP/Docker/Hermes tests. No live balance, credit movement, customer PII, real telco APIs, RAG, LLM classification, dynamic plugins, message broker, PostgreSQL, multi-worker scaling, or separate production gateway. Synthetic demo session IDs are NOT end-user authentication.

**Safety invariants:** the customer/model never specifies authoritative state or action permissions; only CSOL code changes state; mock transactions are private Python functions, never registered as MCP tools; confirmation must be explicit and exact; no success wording until the transaction record is `SUCCEEDED`; unknown/timeout is never success and must not cause blind retries. Do not treat Hermes instructions, MCP tool hints or returned `allowed_actions` as authorization. MCP alone cannot force Hermes to call a tool or to show an approved reply.

**Simplicity:** prefer Python standard library, official compatible pinned MCP SDK, Pydantic, PyYAML, pytest, and `sqlite3`. Use plain functions and one small SQLite store; avoid premature abstractions. YAML describes catalog, route words and state sequences; Python enforces every invariant. Restrict potentially destructive Hermes built-in tools in the deployed customer-service profile.

**Execution discipline:** work ONLY on the numbered stage requested; keep earlier tests passing; do not anticipate later stages. For the stage, implement the smallest working change, add automated tests, run them, report exactly which commands passed/failed, list touched files, and STOP for review. Never report a control as implemented without a passing test. If a dependency/interface is incompatible, report the observed error and make the smallest viable correction; do not silently weaken security to make tests pass.

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
