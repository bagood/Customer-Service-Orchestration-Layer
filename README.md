# Customer Service Orchestration Layer

CSOL serves a six-step customer service procedure over Streamable HTTP at `/mcp`. Redis tracks each conversation, and PostgreSQL records customer names, package offers, and wallet transactions.

## Start CSOL

1. Copy `.env.example` to `.env` beside `compose.yaml`. Set `REDIS_URL` and `DATABASE_URL` to endpoints reachable from the container. Generate a private `CSOL_BINDING_KEY` of at least 32 bytes with `python -c "import secrets; print(secrets.token_hex(32))"`. Share the key with the trusted client service that signs conversation bindings.
2. Confirm the PostgreSQL contract with the service owner. CSOL expects `csol.customers`, `csol.packages`, and `csol.operations` as defined in [the fixture schema](tests/fixtures/schema.sql). Credits and GB are whole numbers. The runtime role needs to read the catalog, lock a quoted package row, read and update customers, and read and insert operations. The database owner provisions the schema and test accounts.
3. Start the application from the repository root.

```sh
docker compose config --quiet
docker compose up --build -d
```

Compose publishes the application on `127.0.0.1:8000`. A client deployed separately needs a CSOL URL reachable from its network.

## Connect an external client

The client signs a short-lived JWT with HS256 and the shared `CSOL_BINDING_KEY`. Include `aud: csol`, `exp`, the session ID in `sub`, the authenticated customer ID in `customer`, and a customer-turn ID in `turn`. Reuse the session ID across turns and the turn ID across calls made within one customer turn.

Call `GET /scope` with the JWT as a bearer token to get the four allowed tool names and the current revision. Use that list to scope the stable catalog exposed by `/mcp`. The first tool reads the current instruction and the second runs the step action. Pass the JWT as the `binding` argument on every tool call and the current revision on actions. A top-up with a retained offer requires purchase confirmation from a later customer turn.

## Verify the journeys

Run the offline workflow and HTTP protocol tests with Python 3.12.

```sh
uv sync --frozen
uv run --frozen pytest -q
```

For the database checks, point `CSOL_TEST_DATABASE_URL` and `CSOL_TEST_REDIS_URL` at dedicated test services. The PostgreSQL database must already contain the fixture schema. The tests create uniquely identified customers and packages and remove their records afterward. They exercise competing purchases, duplicate deliveries, catalog changes, and failure between the PostgreSQL commit and the Redis transition.

Initialize a new disposable test database with the fixture schema before running the suite.

```sh
psql "$CSOL_TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/fixtures/schema.sql
uv run --frozen pytest -q
```

## Recover a pending transaction

Redis reserves the action and its validated arguments before dispatch. PostgreSQL locks the customer row and records a stable operation ID with the outcome in the same transaction as the balance change. After a service interruption, read the current instruction. If Redis still has an in-flight action, retry the recorded tool, arguments, and revision. CSOL checks for the committed outcome before applying a balance change and then finishes the Redis transition. A changed command at that revision is rejected.

For a manual check, query `csol.operations` by `operation_id`. The ID combines the Redis conversation's `instance`, a period, and its action revision. The receipt contains the signed balance change and the posted balance. Service owners should confirm this lookup and the schema contract before connecting a live wallet.

## Author a workflow

Create `workflow/<workflow_id>/workflow.yaml` and one directory per step. The workflow and step directory names are the IDs persisted in Redis. Use Python identifiers for IDs and aliases. Aliases are local to the manifest, so changing an alias does not change a stored step ID. Reference cross-workflow destinations by workflow ID and the target's step alias. Add a destination to an existing workflow only when it needs to route to the new workflow.

For example, this manifest in `workflow/check_status/workflow.yaml` declares one step and a return route.

```yaml
version: 1
context:
  checked: {type: boolean, default: false}
reset_on_return_to_menu: [checked]
steps:
  check: {directory: check_account}
destinations:
  menu: {workflow: landing, step: menu}
```

Put the question in `workflow/check_status/check_account/instruction.md` and export a `Step` from the directory's `main.py`. The exported handler names become MCP tool names, so choose globally unique names and keep them stable while stored conversations or reservations still refer to them.

```python
from app.model import Action, Step


def status_instruction(workflow):
    return workflow.instruction_text


async def acknowledge_status(conversation, args, db, turn, workflow):
    """Acknowledge the status and return to the service menu."""
    workflow.context()["checked"] = True
    workflow.move("menu")
    return {"outcome": "status_acknowledged"}


step = Step(status_instruction, acknowledge_status, Action)
```

The registry loads manifests at startup. It requires one `start_at` and one `return_to_menu_at` across the registry, each pointing to a local step alias. Use one YAML document per file with explicit values. Duplicate keys, tags, anchors, aliases, and merge keys are rejected. Every directory containing a step's `main.py` must be declared and have a nonempty instruction file. Keep action input schemas, conditions, and handlers in Python.

Context supports strings, integers, booleans, and typed objects. Use `nullable: true` to accept null, `minimum` or `maximum` to constrain integers, and `default` to supply an initial value. Objects reject undeclared keys and require fields that have no default. Read values through `workflow.context()` and assign edited objects back through that accessor. To read or write another workflow's fields, list them under `context_dependencies` and use `workflow.context("other_workflow")`. To include context values in instruction responses, define `export_context(workflow)` in the workflow's `__init__.py` and return a mapping of the values to expose. Values are private by default. A confirmed global menu return reverts each manifest's listed reset fields to their defaults, or removes them if no default was declared.

## Redis storage

Start with an empty Redis database or one containing CSOL conversation envelopes written by this application. Each record stores `version: 1`, the conversation's state and revision, pending actions, and workflow context under `context.<workflow_id>`. CSOL rejects invalid records and unsupported versions without replacing them.

The PostgreSQL schema is unchanged. Keep state IDs, step IDs, and tool names stable while conversations or pending operations still reference them.
