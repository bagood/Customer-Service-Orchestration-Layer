# Customer Service Orchestration Layer

CSOL serves a six-step customer service procedure over Streamable HTTP at `/mcp`. Hermes speaks to the customer. Redis tracks each conversation, and PostgreSQL records customer names, package offers, and wallet transactions.

## Start CSOL

1. Copy `.env.example` to `.env` beside `compose.yaml`. Set `REDIS_URL` and `DATABASE_URL` to endpoints reachable from the container. Generate a private `CSOL_BINDING_KEY` of at least 32 bytes with `python -c "import secrets; print(secrets.token_hex(32))"`. Hermes uses the same key to sign its conversation, customer, and turn identifiers.
2. Confirm the PostgreSQL contract with the service owner. CSOL expects `csol.customers`, `csol.packages`, and `csol.operations` as defined in [the fixture schema](tests/fixtures/schema.sql). Credits and GB are whole numbers. The runtime role needs to read the catalog, lock a quoted package row, read and update customers, and read and insert operations. The database owner provisions the schema and test accounts.
3. Start the application from the repository root.

```sh
docker compose config --quiet
docker compose up --build -d
```

Compose publishes the application on `127.0.0.1:8000`. Hermes on the Docker host uses `http://127.0.0.1:8000` as its base URL. Hermes on the same Docker network uses `http://csol:8000`.

## Connect Hermes

The customer service profile targets Hermes **v2026.9.24** (commit `f97608f178d1ffeca59860195ab7da295f7c8e5f`). The server pins MCP Python SDK 1.30.0. The pinned Hermes client uses its own SDK. Install the profile in a fresh directory and configure a tool-capable Chat Completions model in that profile.

```sh
git clone --branch v2026.9.24 --depth 1 https://github.com/NousResearch/hermes-agent.git /path/to/hermes-agent
uv sync --project /path/to/hermes-agent --python 3.12 --frozen --no-dev --extra mcp
export HERMES_HOME=/path/to/customer-service-profile
mkdir -p "$HERMES_HOME"
cp -R hermes/profile/. "$HERMES_HOME/"
```

In the profile's private `.env`, set `CSOL_URL` to the base URL above, `CSOL_BINDING_KEY` to the same signing key, and `CSOL_CUSTOMER_ID` to an existing test customer's ID. Configure the model/provider in this dedicated profile, then run `/path/to/hermes-agent/.venv/bin/hermes chat`. The supplied profile uses one test wallet across sessions. A multi-customer channel must supply its authenticated account ID at the adapter's binding function.

The profile registers `csol` under `mcp_servers`. Before each inference its middleware asks `/scope` for the current session's four tool names. It filters the model's schemas, selects the instruction function at the start of a customer turn, and injects the signed binding on execution. The profile disables Hermes tool search and handles its unknown-tool recovery message. CSOL checks the binding, current step, expected revision, and pending confirmations on every action. A top-up with a retained offer requires a purchase confirmation from a later customer turn.

## Verify the journeys

Run the offline workflow and HTTP protocol tests with Python 3.12.

```sh
uv sync --frozen
uv run --frozen pytest -q
```

For the database checks, point `CSOL_TEST_DATABASE_URL` and `CSOL_TEST_REDIS_URL` at dedicated test services. The PostgreSQL database must already contain the fixture schema. The tests create uniquely identified customers and packages and remove their records afterward. They exercise competing purchases, duplicate deliveries, catalog changes, and failure between the PostgreSQL commit and the Redis transition.

For a new **disposable** PostgreSQL database, the service owner can initialize the contract and seed the Hermes demonstration with these commands.

```sh
psql "$CSOL_TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/fixtures/schema.sql
psql "$CSOL_TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/fixtures/demo.sql
uv run --frozen pytest -q
```

With CSOL running and the customer service profile active, set `CSOL_CUSTOMER_ID=demo-wallet`. The scripted acceptance run uses the actual Hermes agent, plugin, MCP client, and application. It substitutes deterministic responses at the model boundary. Run it once per freshly seeded wallet.

```sh
/path/to/hermes-agent/.venv/bin/python tests/hermes_journey.py
```

For a customer-driven check, start two fresh chats. Give a name in the first and check that the other still asks for identification. In the first chat, request the streaming package, accept the 50-credit quote, agree to add credits, and add 30. Check that Hermes reports 50 credits and asks again before purchasing. Confirm the offer. These queries should show a zero balance, one top-up receipt, and one purchase receipt.

```sql
SELECT name, balance FROM csol.customers WHERE customer_id = 'demo-wallet';
SELECT kind, result->'receipt' AS receipt
FROM csol.operations WHERE customer_id = 'demo-wallet' AND result ? 'receipt';
```

The Redis key `csol:conversation:<Hermes session ID>` contains the current state, step, revision, and temporary context. After recording a name, run `docker compose up -d --force-recreate csol` and resume the same session. The menu instruction should retain the name and revision. After the full purchase journey the first chat should be at `landing / intent_classification`.

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

## Roll out the Redis format

1. Deploy this release to all instances with `CSOL_CONVERSATION_WRITE_FORMAT=legacy` (the default). It reads both formats and writes the flat record. Verify the six existing steps and retained conversations before proceeding.
2. Switch all writers together to `CSOL_CONVERSATION_WRITE_FORMAT=versioned`. Reads preserve the stored record. The next successful reservation or transition writes the versioned envelope at the same Redis key. Conversion itself does not advance the revision.
3. Keep this compatibility release as the rollback target. To roll back, switch writers back to `legacy`. The compatibility release can still resume already converted conversations and writes them in the flat format on their next update. Retire that rollback target before deploying workflows with new persisted states or context fields. Startup rejects such extensions while legacy writes are active.

The PostgreSQL schema is unchanged. Keep the existing state IDs, step IDs, and tool names stable while conversations or pending operations still reference them.
