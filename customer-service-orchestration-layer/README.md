# Customer Service Orchestration Layer (CSOL)

CSOL is an independent Python project for a simulated telecom customer-service
MCP server. Hermes Agent will act as its MCP client.

**Stage 00 status:** installable package, pinned development dependencies, an
offline YAML sample, and two foundation tests. There is no running server,
authentication, router, state machine, database, transaction gateway, or Hermes
connection in this stage. No credentials or real service access are needed.

## Intended message flow

```text
customer
  → Hermes channel
  → Hermes MCP client
  → CSOL MCP server (private Streamable HTTP endpoint /mcp)
  → private mock gateway + SQLite
  → canonical reply
  → Hermes channel
```

The gateway and SQLite will remain private implementation details of CSOL.
CSOL will never call Hermes `/v1/chat/completions` or modify Hermes source.
Future Hermes integration will add only a configuration snippet/profile under
`hermes/`, for merging into the deployed Hermes persistent configuration.

## Scope and limits

The eventual MVP covers only simulated `buy_package` and `send_credit`
workflows, a deterministic router, a controller-owned FSM, SQLite, safe reply
templates, basic MCP transport authentication, and MCP/Docker/Hermes tests.
Stage 00 does not implement these later-stage features.

Non-goals include live balances or credit movement, customer PII, real telecom
APIs, RAG, LLM classification, dynamic plugins, message brokers, PostgreSQL,
multiple workers, and a separate production gateway.

Two hard limits apply to the design:

1. Model-mediated MCP calls are not mandatory. MCP cannot force Hermes to call
   CSOL for each customer message.
2. Final Hermes text cannot be forcibly approved by CSOL. An independent outbound
   gate would be required to enforce an approved final reply; that gate is
   outside this MVP.

MVP success criterion: in the completed MVP, scripted synthetic scenarios for
both workflows should reach a recorded `SUCCEEDED` transaction only after exact,
explicit confirmation and return the matching canonical reply. Unknown or timed
out transactions must not produce success wording or trigger blind retries.
Stage 00 establishes only the import and configuration test baseline; it does
not yet demonstrate this workflow criterion.

**Production safety disclaimer:** this is an offline simulation foundation,
not a production customer-service system. It is not ready for real customers,
PII, funds, or credit. Synthetic session IDs do not authenticate customers.
The later controller must own state and permissions; model-supplied state,
Hermes instructions, MCP tool hints, and returned `allowed_actions` cannot grant
authorization. Mock transaction functions must remain private Python functions,
never MCP tools. Potentially destructive Hermes built-in tools must be restricted
in the deployed customer-service profile. These are requirements for later
stages, not controls implemented here.

## Tested versions

The exact development interpreter is **CPython 3.12.13**, recorded in
`.python-version`. Package metadata permits Python 3.11+, but only the pinned
interpreter is the Stage 00 verification target.

| Dependency | Pin | Purpose |
| --- | --- | --- |
| Official MCP Python SDK (`mcp`) | 1.30.0 | SDK v1 import compatibility |
| Pydantic | 2.14.3 | Validation dependency baseline |
| PyYAML | 6.0.3 | Safe parsing of the offline sample |
| pytest | 9.2.0 | Offline foundation tests |
| setuptools | 78.1.1 | Isolated package build backend |

`requirements.txt` is the single source of the four direct dependency pins;
`pyproject.toml` reads it during installation. pytest is included in this small
development foundation. setuptools is pinned separately in the build-system
configuration. Transitive dependency versions are resolved by pip; this stage
does not provide a complete transitive lockfile.

The MCP pin deliberately selects the supported v1 line and its `FastMCP`,
`ClientSession`, and `streamablehttp_client` imports. The [official v1 package
documentation](https://pypi.org/project/mcp/1.30.0/) describes Streamable HTTP
support; the [tagged dependency metadata](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/pyproject.toml)
requires Pydantic 2.11+ and below 3 on Python 3.12. SDK v2 has breaking changes;
use the [v1 documentation](https://py.sdk.modelcontextprotocol.io/v1/) for this
pin. No SDK connection or server is started by the import check or tests.

## Setup and verification

From the directory containing the stage prompts, enter this project. All
remaining commands run from `customer-service-orchestration-layer/`, the
independent repository root.

Use a Python version manager of your choice to make CPython 3.12.13 available as
`python3.12`, then run on macOS/Linux:

```sh
cd customer-service-orchestration-layer
python3.12 --version  # Expected: Python 3.12.13
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m pip check
python -m pytest -q
python -c "import csol"
```

The editable install makes `csol` importable outside pytest, without setting
`PYTHONPATH`. It also installs the dependencies from `requirements.txt`. Internet
access is needed for the initial dependency installation; tests run offline.
Stage 00 does not load `.env` files or require copying `.env.example`.

The command used to verify all requested imports and the SDK v1 interfaces is:

```sh
python -c "import csol, mcp, pydantic, yaml, pytest; from mcp import ClientSession; from mcp.server.fastmcp import FastMCP; from mcp.client.streamable_http import streamablehttp_client; print('All foundation imports OK')"
```

The expected test result is `2 passed`; `python -c "import csol"` exits
successfully with no output. The smoke test checks package and SDK interface
imports. The configuration test reads `configs/example.yaml` with
`yaml.safe_load` and checks the offline values, including the integer stage.

## Project layout

```text
customer-service-orchestration-layer/
├── .env.example
├── .gitignore
├── .python-version
├── configs/example.yaml
├── data/.gitkeep
├── hermes/.gitkeep
├── scripts/.gitkeep
├── src/csol/__init__.py
├── tests/test_config.py
├── tests/test_smoke.py
├── pyproject.toml
├── pytest.ini
├── requirements.txt
└── README.md
```

`hermes/` and `scripts/` are reserved for later stages. `data/` is reserved for
local generated data; only its placeholder belongs in source control. The ignore
rules cover virtual environments, local environment files and secret directories,
private key files, SQLite databases and their sidecars, and generated output.
Keep future credentials in the ignored locations rather than committed examples.
