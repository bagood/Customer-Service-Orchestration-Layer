# Customer Service Orchestration Layer (CSOL)

CSOL is an independent Python MCP server for a simulated telecom customer-service
assistant. Hermes Agent is the MCP client. The private Streamable HTTP endpoint
is `/mcp` on port 8000.

**Stage 06 status:** private Docker deployment and integration with the existing
Hermes gateway, in addition to authenticated MCP connectivity, strict input/output validation,
deterministic bilingual routing, versioned configuration, and persistent SQLite
session state. Both package purchase and credit transfer validate collected inputs
and a typed simulation balance, require exact confirmation, record a private mock
transaction, and collect optional feedback before returning to the menu. Persisted
response replay, serialized confirmation, version checks, durable transaction
reservations, and adversarial/crash tests harden both workflows. See the
[private Docker/Hermes runbook](docs/private_docker_hermes.md) and
[Stage 06 verification](docs/stage_06_verification.md) for actual compatibility,
commands, test results and the customer-to-ledger trace.

## Setup

Run these commands from `customer-service-orchestration-layer/` using CPython
**3.12.13**, recorded in `.python-version`:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m pip check
python -m pytest -q
```

Package metadata permits Python 3.11+, but 3.12.13 is the tested interpreter.
`requirements.txt` supplies the direct dependency pins to `pyproject.toml`:

| Dependency | Pin | Purpose |
| --- | --- | --- |
| Official MCP Python SDK | 1.30.0 | Streamable HTTP server and client |
| Pydantic | 2.14.3 | Strict tool input/output models |
| PyYAML | 6.0.3 | Safe loading of route and workflow configuration |
| pytest | 9.2.0 | Automated verification |
| Starlette | 1.10.0 | ASGI application and test client |
| Uvicorn | 0.54.0 | HTTP server |
| HTTPX | 0.28.1 | Official MCP client's HTTP transport |

The build backend remains pinned to setuptools 78.1.1. Transitive dependencies
are resolved by pip; this stage has no complete transitive lockfile.

## Run the server and live smoke test

Inject a secret token into the server environment. It must contain 32–512
characters from `A-Z`, `a-z`, `0-9`, `_`, `~`, and `-`. Generate a value once:

```sh
export CSOL_BEARER_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Start the server in that shell:

```sh
.venv/bin/python -m csol.server
```

The SQLite file defaults to `data/csol.sqlite3`, independent of the current
directory. Optionally export `CSOL_DB_PATH=/absolute/path/to/csol.sqlite3`
before starting. Its parent directory is created automatically. Relative
overrides resolve from the working directory. Keep this file across restarts
and use a single server process. Database files and journals are gitignored.

In a second shell with **the same token injected**, run the official MCP client:

```sh
.venv/bin/python scripts/mcp_smoke.py --url http://127.0.0.1:8000/mcp
```

The script initializes MCP, verifies that discovery exposes exactly
`csol_process_turn`, calls it, validates the structured response, and prints
`MCP smoke: PASS`. It exits nonzero on failure. The token is read from the
environment, never a command-line argument. `.env.example` documents the
variable; bare Python does not load `.env` automatically (Compose does). Keep actual secrets out of Git.
Missing or malformed server configuration prevents startup.

The server binds `0.0.0.0:8000` for the intended private service network. The
default Compose deployment publishes no host port and uses the internal
`csol-private` bridge; use an authorized client container for its smoke test.
It uses one worker, disables proxy-header trust, and does not configure TLS.

## Tool contract

Only one MCP tool is registered:

```text
csol_process_turn(session_ref, message_id, message)
```

All three arguments must be strings containing at least one non-whitespace
character. Identifiers are limited to 128 characters and `message` to 1000.
Unexpected fields are rejected, including supplied state, permissions, and
transaction data. The MCP discovery schemas are generated from the same
Pydantic models used for validation.

For `message: "buy package"` in a new synthetic session, the tool returns:

```json
{
  "session_ref": "demo-buy",
  "mode": "buy_package",
  "state": "SELECT_PACKAGE",
  "state_version": 1,
  "customer_reply": "Package demo selected. Catalog: A Rp 10,000; B Rp 20,000. Select A/B or 1/2. Type cancel or batal to return to the menu. No transaction has been executed.",
  "allowed_actions": ["cancel"],
  "transaction": null,
  "simulated": true,
  "safe_to_display": true
}
```

An idle session returns `mode: "demo"`, `state: "IDLE"` and actions
`["buy_package", "send_credit"]`. Active sessions return their workflow as
`mode` and `["cancel"]`, except pending/unknown transactions return no actions
and hold the workflow for manual review. Actions are descriptive metadata and do not grant
authorization. MCP transport sessions remain stateless; application sessions
persist in SQLite. There are no exported purchase, transfer, state-setting,
or backend tools, and no `/chat` or `/v1/chat/completions` API.

Tool errors have MCP `isError: true` and the same validated response fields,
with `mode: "error"`, `state: "UNAVAILABLE"`, no actions or transaction, a fixed
safe reply, and one of these `error_code` values:

| Code | Meaning |
| --- | --- |
| `INVALID_ARGUMENTS` | Missing, extra, wrong-type, empty, or oversized tool fields; `session_ref` is null |
| `SERVER_UNAVAILABLE` | Internal handler failure or invalid output; validated session reference is preserved |
| `UNKNOWN_TOOL` | Unregistered tool name; `session_ref` is null |

Failure responses do not expose exception details. Their `state_version: 0`
is an error sentinel, not a saved state reset. Output models forbid extra
fields, bound strings, require nonnegative integer state versions, and constrain
simulation and safe-display flags, and allow a transaction receipt only with a
positive integer `transaction_id` and `status: "SUCCEEDED"`. The controller reads
that recorded status before producing the canonical demo success reply. Invalid
arguments and unauthenticated turns do not mutate sessions or audit. An internal
error reports an unconfirmed outcome and instructs the caller not to retry
automatically; it does not assert that execution was impossible.

## Routing and persisted state

`configs/global.yaml` contains only the two route groups. Matching applies Unicode
NFKC normalization, case folding, and whitespace collapsing, then matches exact
phrases at word boundaries. For example, `BUY   PACKAGE` matches; `buy packages`
and `rebuy package` do not. Supported phrases include `beli paket`, `buy package`,
`transfer pulsa`, `kirim pulsa`, `send credit`, and the two workflow identifiers.
This is keyword matching, not semantic or LLM intent classification.

Routing happens only from `IDLE`:

| Input | Saved state | Reply behavior |
| --- | --- | --- |
| `beli paket` / `buy package` | `SELECT_PACKAGE` | Show demo catalog A/B |
| `transfer pulsa` / `send credit` | `ENTER_MSISDN` | Request a synthetic mobile recipient |
| Both intents | `IDLE` | Ask which workflow to do first |
| Unsupported input | `IDLE` | Show the two-option menu |
| Exact normalized `cancel` / `batal` | `IDLE` | Clear the active workflow and data; show menu |

Once active, ordinary messages, including route words, are responses to the
saved workflow state. They never globally switch workflows. Both workflows
are validated by the FSMs below.
Cancellation matches the entire normalized message; `cancel now` is not a reset.
Before execution it returns to the menu without creating a transaction; at
feedback it records a skipped response and preserves the completed transaction.

`configs/workflows/*.v1.yaml` defines workflow IDs, version 1, their state sequences,
and the package catalog (`A = Rp 10,000`, `B = Rp 20,000`). All definitions are
parsed with the safe YAML loader and validated before the database or MCP
transport is constructed. Python requires the exact implemented sequences and
fixed demo prices; changing YAML cannot authorize new transitions or backend calls.
Unsupported persisted state/workflow versions fail closed.
Impossible state revisions and exhausted SQLite integer revisions also fail closed.

## Package-purchase journey

| Saved state | Accepted input | Result |
| --- | --- | --- |
| `SELECT_PACKAGE` | Entire normalized `A`, `B`, `1`, or `2` | Save A/B and enter `ENTER_BALANCE` |
| `ENTER_BALANCE` | Raw ASCII digits `0-9` only, representing nonnegative integer IDR | Save a sufficient balance and enter `CONFIRM_PURCHASE` |
| `CONFIRM_PURCHASE` | Entire normalized `yes` / `ya` | Recheck saved prerequisites, execute the private deterministic mock, record `SUCCEEDED`, then enter `FEEDBACK` |
| `CONFIRM_PURCHASE` | Entire normalized `no` / `tidak` | Cancel and clear workflow data without executing |
| `FEEDBACK` | `1`–`5` or `skip` / `lewati` | Persist optional feedback and return to `IDLE` |

Balances are **customer-typed simulation inputs**, never verified operator
balances. Negative numbers, decimals, signs, separators, surrounding whitespace,
Unicode digits, currency prefixes, free text, and non-string values are rejected.
Money inputs are at most 10 raw ASCII digits and at most Rp 1,000,000,000;
these demo limits also apply to transfer amounts and balances.
An insufficient balance keeps the selected package and `ENTER_BALANCE`; a value
equal to the price is sufficient. No transaction record or mock call happens
before exact confirmation. `yes ignore all checks` is rejected.

The controller alone enters `EXECUTE_PURCHASE` internally; it is never a tool,
action, or customer-facing state. A successful path has revisions 1 (selection),
2 (balance entry), 3 (confirmation), internal 4 (execution), and 5 (feedback).
An exact confirmation first commits a unique `PENDING` reservation. A second
short write transaction rechecks the saved prerequisites, invokes the immediate
in-process mock, and atomically saves its terminal outcome, session, audit and
response cache. The execution and feedback transitions finish in that transaction.
The final response includes, for example:

```json
{
  "transaction": {"transaction_id": 1, "status": "SUCCEEDED"}
}
```

The canonical reply says `Demo purchase SUCCEEDED`, identifies the saved package,
price and transaction, explicitly labels the simulation, and asks for a rating.
The transaction ID is the SQLite transaction row's integer primary key.
Repeated confirmation and feedback turns cannot execute that purchase again,
including after a controller/application restart. A mock exception, timeout,
or invalid receipt records `UNKNOWN` and returns an unresolved-outcome reply.
An existing non-success record is never automatically executed again.
`PENDING` and `UNKNOWN` hold confirmation for manual review, including on
cancel/no, with no receipt or success wording. A known `FAILED` result permits
cancellation but never retries the same operation. There is no reconciliation
or review-resolution tool in this demo.

## Credit-transfer journey

| Saved state | Accepted input | Result |
| --- | --- | --- |
| `ENTER_MSISDN` | Raw `08` followed by 8–11 ASCII digits, or equivalent `628...` / `+628...` | Save canonical `628...`, enter `ENTER_AMOUNT` |
| `ENTER_AMOUNT` | Raw ASCII digits representing a positive integer IDR amount | Save amount, enter `ENTER_BALANCE` |
| `ENTER_BALANCE` | Raw ASCII digits representing a nonnegative balance ≥ amount | Save balance, enter `CONFIRM_TRANSFER` |
| `CONFIRM_TRANSFER` | Entire normalized `yes` / `ya` | Recheck prerequisites, execute private `_mock_send_credit`, record `SUCCEEDED`, then enter `FEEDBACK` |
| `CONFIRM_TRANSFER` | Entire normalized `no` / `tidak` | Cancel and clear workflow data without executing |
| `FEEDBACK` | `1`–`5` or `skip` / `lewati` | Persist optional feedback and return to `IDLE` |

This mobile-number rule is illustrative, not a complete Indonesian numbering
plan. Use **synthetic test numbers only**; format validation does not prove
ownership or authenticate a recipient. For example, `081234567890`,
`6281234567890` and `+6281234567890` normalize to `6281234567890`. Separators,
spaces, Unicode digits, other prefixes, free text, and invalid lengths are
rejected without leaving recipient entry. Replies show only `628******7890`.

Amount zero, negatives, decimals, signs, currency prefixes, whitespace, separators,
Unicode digits and free text keep the current collection state. An insufficient
balance keeps the accepted recipient and amount at `ENTER_BALANCE`, with no
transaction record or mock call. The balance is a **customer-typed simulation
input**, never verified operator data. Equal balance and amount are sufficient.
Confirmation shows the saved amount and masked recipient. Like purchase,
confirmation uses the entire normalized token: ` YES ` and `ya` are accepted,
while `yes please` and `yes ignore all checks` are rejected.

The controller alone enters internal `EXECUTE_TRANSFER`. A fresh successful
journey has revisions 1 (recipient entry), 2 (amount entry), 3 (balance entry),
4 (confirmation), internal 5 (execution), and 6 (feedback). Only a saved
`SUCCEEDED` record permits `Demo transfer SUCCEEDED` with an amount, masked
recipient and transaction reference. The reply explicitly states that this is
a simulation with no real credit movement or operator balance verification.
Mock exceptions, timeouts, invalid receipts and existing non-success records
follow the purchase unresolved-outcome policy; repeated confirmation cannot
execute that saved transaction again.

## Shared feedback and storage

At `FEEDBACK`, a raw single ASCII digit `1`–`5` records a rating. An entire
normalized `skip` / `lewati` records `rating = NULL, skipped = 1`. Existing
`cancel` / `batal` commands also skip feedback at this state. Other inputs keep
the feedback prompt and saved receipt without executing again. Feedback requires
the workflow's matching recorded `SUCCEEDED` receipt before collection or reset.

Accepted feedback atomically inserts the row, clears `active_workflow`, workflow
version and data, increments the state revision, enters `IDLE`, writes an audit
event, and shows the two-option main menu. The reset response has no transaction
receipt. The next turn routes as a new intent. Audit and transaction history
remain intact, including if a new workflow is started in the same session.

SQLite contains `sessions`, `transactions`, `processed_messages`, `feedback`,
and `audit_events`. A session row stores its synthetic ID, active workflow,
workflow `version`, `state`, `state_version`, `data_json`, and UTC `updated_at`.
Purchase data contains the selected package, then accepted balance, then
transaction reference. Transfer data contains the canonical synthetic recipient,
then amount, accepted balance and transaction reference. New sessions start at
revision zero. Each controller
state transition increments `state_version`; menu and held-state turns keep it.
Each valid turn saves its session and a minimal audit event atomically, returning
the saved state and revision. Audit records contain synthetic session references,
fixed event labels, states, revision, and time, without raw messages, message
IDs, recipients, or bearer tokens.

Transactions use one unique key per workflow, synthetic session, workflow version, and
confirmation revision. The existing Stage 02 schema needs no migration.
The feedback and processed-message tables are populated. Every completed valid
turn atomically records its validated response under the SQLite primary key
`(session_id, message_id)`. Repeating that pair returns the original response,
even if the message text or current workflow has changed, without updating any
table. Use a new message ID for each distinct turn and retain the same ID for
delivery retries. Cache keys contain synthetic message IDs; raw messages are
never stored. Cached success receipts require a still-recorded `SUCCEEDED` row.

All mutations use `BEGIN IMMEDIATE`, a one-second SQLite lock wait, and no
application retry loop. Session writes compare the expected saved revision;
transaction keys remain UNIQUE independently of message IDs. Fresh databases
also constrain status to `PENDING / SUCCEEDED / FAILED / UNKNOWN`; existing
databases retain their schema, with the same status checks enforced in Python.
No table rebuild or data migration is needed.

Committing the reservation before invocation prevents final persistence failure
or a crash from erasing the invocation fence. Such a failure leaves `PENDING`
for review across restarts, even if the mock already returned success. A repeat
that records a pending reply in the small reservation/lock-reacquisition gap
also conservatively holds that operation without invoking it. Other fresh
confirmation IDs share the original transaction key. There are no automatic
financial retries or background recovery. Only immediate local mocks run while
the write lock is held; this is not a pattern for live network calls.

Runtime logs contain fixed error/event codes, states and revisions without
customer text, session/message IDs, recipients, balances or tokens. Persisted
audit records retain synthetic session references and controller transitions.
Session references must be synthetic; they are not customer
identity or ownership checks.

## HTTP security policy

Every HTTP request to `/mcp` requires `Authorization: Bearer <token>`.
Authentication uses constant-time secret comparison and runs before request
body parsing, MCP initialization, discovery, or tool execution. Missing,
incorrect, malformed, and duplicate authorization headers receive HTTP 401
with `error_code: "UNAUTHORIZED"` and a Bearer challenge. Query parameters
cannot supply credentials. This is service-to-service authentication, not
end-user identity or OAuth.

The [pinned SDK's transport-security API](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/transport_security.py)
keeps DNS rebinding protection
enabled with exact allowlists:

| Header | Allowed values |
| --- | --- |
| Host | `csol:8000`, `127.0.0.1:8000`, `localhost:8000`, `[::1]:8000` |
| Origin, when present | `http://csol:8000`, `http://127.0.0.1:8000`, `http://localhost:8000`, `http://[::1]:8000` |

Native MCP clients may omit Origin. An invalid Host receives 421; an invalid
Origin receives 403. Other ports and arbitrary origins are rejected. The SDK
also enforces a 16 KiB request-body limit (413), including streamed bodies
without a Content-Length header. Malformed JSON and incorrect Content-Type
are rejected. Unknown paths return 404.

## Verification and limits

```sh
.venv/bin/python -m pytest -q
```

The suite includes the two unchanged Stage 00 tests and tests the real ASGI
application with the official MCP client, authentication, discovery, strict
schemas, safe errors, Host/Origin rejection, payload limits, bilingual and
word-boundary routing, ambiguity, active-state handling, restart persistence,
cancel, configuration rejection, and atomic state/audit writes. It runs offline,
uses temporary databases, and does not require a token in your shell.
The original `configs/example.yaml` remains a Stage 00 offline fixture.
Purchase tests cover the Stage 03 acceptance gate, prerequisite revalidation,
recorded success before success wording, unresolved outcomes, restart persistence,
and a complete journey through the official MCP client and real ASGI application.
Transfer and shared-feedback tests cover prefix normalization, malformed input,
amount/balance validation, masked replies, exact confirmation, recorded outcomes,
restart persistence, rating/skip reset, preserved history, and a complete transfer
journey through the official MCP client. See
[Stage 05 verification](docs/stage_05_verification.md) for the safety checklist,
exact test names, commands, touched files, crash policy and production limits.
Historical reports record [Stage 04](docs/stage_04_verification.md), including both workflow traces,
[Stage 03](docs/stage_03_verification.md), [Stage 02](docs/stage_02_verification.md)
and [Stage 01](docs/stage_01_verification.md).

End-customer identity binding and outbound reply gating remain absent. The cross-session test explicitly
demonstrates that another bearer-authenticated client knowing a synthetic session
reference can confirm that workflow. Separate session rows are not ownership
authorization. CSOL never calls Hermes `/v1/chat/completions` or modifies
Hermes source. Stage 06 supplies configuration fragments, a restricted CLI test
profile and Compose overlays for the existing gateway and its persistent configuration.

The eventual MVP remains limited to simulated `buy_package` and `send_credit`
workflows with a deterministic router, controller-owned FSM, SQLite, private
mock transactions, and safe reply templates. No live balance, credit movement,
customer PII, real telecom APIs, RAG, LLM classification, dynamic plugins,
message brokers, PostgreSQL, multi-worker scaling, or separate gateway.

Synthetic session IDs do not authenticate customers. Only controller code may
change state or permit actions. Purchases and transfers require exact, explicit
confirmation and a recorded `SUCCEEDED` result before success wording; unknown
or timed-out outcomes must not trigger blind retries. MCP cannot force Hermes
to call a tool or display its approved
reply, and returned action lists and tool hints are not authorization.
Potentially destructive Hermes built-ins must be restricted in its deployed
customer-service profile. This demo is not ready for real customers or credit.
