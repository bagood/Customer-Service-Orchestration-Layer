# Customer Service Orchestration Layer

CSOL serves a six-step customer service procedure over Streamable HTTP at `/mcp`. Redis tracks each conversation, and PostgreSQL records customer names, package offers, and wallet transactions.

## Start CSOL

1. Copy `.env.example` to `.env` beside `compose.yaml` and restrict it with `chmod 600 .env`. Generate a private `CSOL_BINDING_KEY` of at least 32 bytes with `python -c "import secrets; print(secrets.token_hex(32))"` and share it with the trusted client that signs conversation bindings.
2. For a fresh setup, generate separate passwords for PostgreSQL and Redis, then build the Redis ACL file from the checked-in template. On the host, keep the files under the private `.secrets` directory. Inside the containers, the PostgreSQL app password and Redis ACL file must be readable by their respective service users.

```sh
(
  umask 077
  mkdir .secrets
  python -c 'import secrets; print(secrets.token_hex(32))' > .secrets/postgres_admin_password
  python -c 'import secrets; print(secrets.token_hex(32))' > .secrets/postgres_app_password
  python -c 'import secrets; print(secrets.token_hex(32))' > .secrets/redis_password
)
python - <<'PY'
from hashlib import sha256
from pathlib import Path

password = Path(".secrets/redis_password").read_bytes().rstrip(b"\n")
template = Path("deploy/redis/users.acl.template").read_text()
Path(".secrets/redis.acl").write_text(template.replace("PASSWORD_SHA256", sha256(password).hexdigest()))
PY
chmod 644 .secrets/postgres_app_password .secrets/redis.acl
```

3. In `.env`, replace the `DATABASE_URL` placeholder with the PostgreSQL app password and the `REDIS_URL` placeholder with the Redis password. For passwords with reserved URL characters, use `urllib.parse.quote(password, safe="")` for the URL. Keep the original single-line passwords in the secret files. Regenerate `.secrets/redis.acl` from the template when changing the Redis password.
4. Start both databases, then start CSOL from the repository root.

```sh
docker compose config --quiet
docker compose up -d --wait postgres redis
docker compose up --build -d csol
```

Compose publishes CSOL on `127.0.0.1:8000`. PostgreSQL listens at `postgres:5432` and Redis at `redis:6379` on the Compose network. Both services use named volumes. CSOL starts after PostgreSQL accepts a query as `csol_app` and Redis replies `PONG` as `csol`.

### Seed development data

Load a demo customer with 20 credits and a 5 GB package priced at 50 credits. Identify as `demo-customer`, top up by at least 30 credits, and search for the package using `CSOL demo data` as the benefit. Reapplying the seed preserves any changes to those demo records.

```sh
docker compose exec -T postgres psql -X -U postgres -d csol -v ON_ERROR_STOP=1 --single-transaction \
  < deploy/postgres/seed/demo.sql
```

### Migrate and back up PostgreSQL

On an empty volume the image creates the `csol` database, then runs the ordered bootstrap as the provisioning administrator. The schema follows [the database fixture](tests/fixtures/schema.sql). The provisioning administrator owns it. The runtime role can read the three tables, update customer names and balances, and insert operation receipts. It also has update permission on `packages.package_id` so PostgreSQL permits the application's `SELECT … FOR SHARE`.

Existing volumes retain their data and roles. Apply later schema changes as numbered SQL migrations under `deploy/postgres/migrations/`. Back up the database first, review the migration, then apply the new files in order using the provisioning role. Record the applied migration versions with the deployment.

```sh
docker compose exec -T postgres pg_dump -U postgres --format=custom csol > .secrets/csol.dump
docker compose exec -T postgres psql -X -U postgres -d csol -v ON_ERROR_STOP=1 --single-transaction \
  < deploy/postgres/migrations/002_description.sql
```

To validate a backup, restore it into a fresh database where the provisioning owner and `csol_app` roles already exist. A database dump contains data and object grants. Provision roles and database-level grants separately when restoring to a new cluster.

```sh
docker compose exec -T postgres createdb -U postgres csol_restore
docker compose exec -T postgres pg_restore -U postgres -d csol_restore --exit-on-error --single-transaction \
  < .secrets/csol.dump
```

Compare the customer balance in `csol.customers` and a known operation's result in `csol.operations` between the source and restored databases. When replacing an existing database, validate customer balances, package data, and operation receipts before changing `DATABASE_URL`.

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

Initialize a disposable database with a separate test login that owns the fixture schema or has read, insert, update, and delete permissions on all three tables. Use a dedicated Redis instance and grant its test user `DEL` for fixture cleanup. The fixture setup command below assumes the login owns the test database. Run the tests from the Compose network or publish the test services on loopback through a local Compose override for host-side tests.

```sh
psql "$CSOL_TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/fixtures/schema.sql
uv run --frozen pytest -q tests/test_conversation_storage.py tests/test_database_journey.py
```

## Recover a pending transaction

Redis reserves the action and its validated arguments before dispatch. PostgreSQL locks the customer row and records a stable operation ID with the outcome in the same transaction as the balance change. After a service interruption, read the current instruction. If Redis still has an in-flight action, retry the recorded tool, arguments, and revision. CSOL checks for the committed outcome before applying a balance change and then finishes the Redis transition. A changed command at that revision is rejected.

For a manual check, query `csol.operations` by `operation_id`. The ID combines the Redis conversation's `instance`, a period, and its action revision. The receipt contains the signed balance change and the posted balance. Service owners should confirm this lookup and the schema contract before connecting a live wallet.

If Redis state is lost, pause wallet-action retries until you reconcile committed PostgreSQL receipts with the affected conversations. A missing Redis record starts a new conversation instance and therefore produces different operation IDs.

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

Redis stores its append-only files in `redis_data`. The default configuration uses `appendfsync always` and `noeviction`. Measure write latency before sending real wallet traffic. With `appendfsync everysec`, a crash can lose roughly one second of acknowledged writes, including action reservations. Conversation keys have no TTL, so monitor key count, memory, and AOF disk usage with deployment monitoring. [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) · [Redis eviction](https://redis.io/docs/latest/develop/reference/eviction/)

Keep state IDs, step IDs, and tool names stable while conversations or pending operations still reference them. When migrating an existing Redis instance, preserve its conversation keys and verify that retained actions resume before switching traffic.

### Back up and restore Redis

Pause incoming traffic, then stop CSOL and Redis before copying the volume. This captures the AOF manifest and every segment from the same point in time. Back up PostgreSQL during the same pause so the Redis reservations can be checked against the corresponding receipts. Keep the archive private because it contains conversation records.

```sh
docker compose stop csol redis
(umask 077 && docker compose run --rm --no-deps -T --entrypoint tar redis -C /data -cf - . > .secrets/redis-data.tar)
(umask 077 && docker compose exec -T postgres pg_dump -U postgres --format=custom csol > .secrets/csol-with-redis.dump)
docker compose up -d --wait redis csol
```

To rehearse a restore, use a new disposable Compose project with an empty Redis volume. The commands below also replace the schema created during PostgreSQL startup with the matching backup. Run CSOL there after freeing its loopback port or rebinding it through a local override.

```sh
docker compose -p csol-restore run --rm --no-deps -T --entrypoint sh redis \
  -ec 'test -z "$(ls -A /data)"; tar -C /data -xf -' < .secrets/redis-data.tar
docker compose -p csol-restore up -d --wait redis postgres
docker compose -p csol-restore exec -T postgres pg_restore -U postgres -d csol \
  --clean --if-exists --exit-on-error --single-transaction < .secrets/csol-with-redis.dump
docker compose -p csol-restore up -d --build csol
```

With a signed binding for an existing session, check `GET /scope` for its recorded step and revision. For a retained wallet reservation, read the conversation record using the `csol` Redis user and find `csol.operations.operation_id` using the record's `instance` and action revision. In the disposable deployment, retry the recorded arguments and verify that CSOL returns the original receipt and the wallet balance stays at the posted value.
