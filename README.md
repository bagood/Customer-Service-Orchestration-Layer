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
