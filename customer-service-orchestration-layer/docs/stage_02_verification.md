# Stage 02 verification

Verified November 8, 2026, using the existing CPython 3.12.13 environment and
MCP SDK 1.30.0. Commands run from `customer-service-orchestration-layer/`.

## Implemented scope

- Two normalized, word-boundary route groups, used only from `IDLE`.
- Controller-owned `buy_package → SELECT_PACKAGE`,
  `send_credit → ENTER_MSISDN`, and exact normalized `cancel` / `batal` reset.
- Version-1 YAML definitions and A/B catalog, validated at startup. Python
  rejects unsupported states and workflow versions.
- One persistent SQLite file with all five requested tables. Each valid turn
  saves the session and a minimal audit event in one SQL transaction, then
  returns the saved state and revision. An in-memory database is rejected.
- Existing authenticated MCP tool, strict inputs/outputs, and transport policy.

There is no purchase FSM, recipient collection, confirmation, mock transaction
function, backend tool, or external service call. Ordinary active-workflow
messages repeat the saved entry prompt. `transactions`, `processed_messages`,
and `feedback` are schema foundations only; controller turns do not write them.
Message replay handling and concurrent-confirmation guarantees remain Stage 05.

## Commands and results

```text
$ .venv/bin/python -m pytest -q
167 passed, 1 warning in 0.91s

$ .venv/bin/python -m pip check
No broken requirements found.

$ git diff --check
(exit 0, no output)
```

The unchanged baseline passed 88 tests before implementation. Stage 01 tests
were retained, with menu-only expectations updated for the intended Stage 02
contract (`IDLE`, persisted sessions, positive state revisions). Authentication,
schema, transport, error, and tool-surface checks remain. The original Stage 00
test functions are unchanged. No dependency pins changed.

The warning is the existing Starlette test-client HTTPX deprecation notice.
`pip check` also reported an unwritable pip cache and disabled the cache; its
dependency check exited zero.

### Four routing tests

`tests/test_routing.py` contains these four tests, parameterized over 31 cases.
Every case checks that the returned state/revision matches its SQLite session
and that no transaction exists.

| Test | Representative input | Expected result |
| --- | --- | --- |
| `test_indonesian_routing` | `Saya ingin beli paket.` / `TRANSFER   PULSA!` | `SELECT_PACKAGE` / `ENTER_MSISDN`, revision 1 |
| `test_english_routing` | `Please buy package!` / `SEND\nCREDIT` | Correct entry state, revision 1 |
| `test_ambiguous_routing_asks_which_first` | `beli paket dan transfer pulsa` | `IDLE`, revision 0, ask which first |
| `test_unsupported_and_partial_words_return_menu` | `check balance`, `rebuy package`, `buy packages` | `IDLE`, revision 0, menu |

Additional cases cover Unicode normalization, workflow-name aliases, and
unsupported/injected state text. Further passing checks include:

- `test_active_workflow_never_globally_reroutes`: both entry states remain
  unchanged for repeated route words, the other intent, A, and yes.
- `test_state_persists_across_controller_restart` and
  `test_mcp_routing_and_cancel_resume_from_same_file_after_app_restart`:
  a new controller/application reads the same database; cancellation resets it.
- `test_exact_cancel_resets_saved_state_and_can_route_again`,
  `test_embedded_cancel_does_not_reset_active_state`, and
  `test_idle_cancel_is_a_safe_noop`: cancellation is exact and safe.
- `test_audit_and_saved_data_exclude_raw_messages_recipients_and_tokens`:
  sentinel message text, a full synthetic recipient, message ID, and token do
  not appear anywhere in the database dump.
- `test_session_and_audit_roll_back_together_on_failure`: a failed audit insert
  rolls back the session change as well.
- Configuration tests reject malformed/unsafe YAML, missing definitions, extra
  route groups, duplicate normalized phrases, unsupported states/versions,
  and invalid catalogs before creating the database.
- `test_unsupported_saved_state_fails_closed_without_mutation`: corrupted or
  unsupported saved states return `SERVER_UNAVAILABLE` without changing rows.
- Existing invalid-auth, invalid-input, and unknown-tool tests now also check
  that all five tables remain empty after rejection.
- Store tests check table/column definitions, foreign-key enablement, the
  unique transaction key, and composite processed-message primary key. Those
  schema-only SQL fixtures do not implement or execute a transaction backend.

## Observed sample session rows

A temporary file was used for six synthetic controller turns. All rows retained
`data_json = "{}"`; timestamps below are stored in UTC. The temporary file was
removed after inspection.

| session_id | active_workflow | version | state | state_version | data_json | updated_at |
| --- | --- | --- | --- | --- | --- | --- |
| demo-ambiguous | NULL | NULL | IDLE | 0 | `{}` | 2026-11-08T11:29:23.049Z |
| demo-buy | buy_package | 1 | SELECT_PACKAGE | 1 | `{}` | 2026-11-08T11:29:23.047Z |
| demo-cancelled | NULL | NULL | IDLE | 2 | `{}` | 2026-11-08T11:29:23.051Z |
| demo-send | send_credit | 1 | ENTER_MSISDN | 1 | `{}` | 2026-11-08T11:29:23.048Z |
| demo-unsupported | NULL | NULL | IDLE | 0 | `{}` | 2026-11-08T11:29:23.049Z |

Observed counts: **0 transactions, 0 processed messages, 0 feedback rows, 6 audit
events**. `demo-cancelled` first started a purchase and then received `batal`.
`version` names the workflow definition; `state_version` counts state changes.

Reproduce with fresh timestamps:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from csol.config import load_configuration
from csol.controller import Controller
from csol.models import TurnInput
from csol.store import Store

with TemporaryDirectory(prefix='csol-stage02-rows-') as directory:
    controller = Controller(Store(Path(directory) / 'sample.sqlite3'), load_configuration())
    cases = [
        ('demo-buy', 'beli paket'),
        ('demo-send', 'send credit'),
        ('demo-ambiguous', 'buy package and transfer pulsa'),
        ('demo-unsupported', 'check balance'),
        ('demo-cancelled', 'buy package'),
        ('demo-cancelled', 'batal'),
    ]
    for index, (session_ref, message) in enumerate(cases):
        controller.process_turn(TurnInput(
            session_ref=session_ref, message_id=f'message-{index}', message=message,
        ))
    with controller.store.transaction() as connection:
        print(json.dumps([dict(row) for row in connection.execute(
            'SELECT * FROM sessions ORDER BY session_id'
        )], indent=2))
        for table in ('transactions', 'processed_messages', 'feedback', 'audit_events'):
            print(table, connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
PY
```

## Live official MCP client

The verification launcher injected a fresh bearer token and temporary
`CSOL_DB_PATH` into both processes, started the server, waited for readiness,
ran the client, and stopped the server in a `finally` block. No token was printed
or committed. The server/client commands were:

```sh
.venv/bin/python -m csol.server
.venv/bin/python scripts/mcp_smoke.py --url http://127.0.0.1:8000/mcp
```

Observed output, exit zero:

```text
initialize: OK (server=csol)
tools/list: OK (csol_process_turn)
tools/call: OK
{
  "session_ref": "demo-smoke-98687d6398de4e3f81c1906883678a85",
  "mode": "demo",
  "state": "IDLE",
  "state_version": 0,
  "customer_reply": "Telecom demo menu (simulation only):\n1. Beli paket / buy package (buy_package)\n2. Transfer pulsa / send credit (send_credit)\nNo transaction has been executed.",
  "allowed_actions": [
    "buy_package",
    "send_credit"
  ],
  "transaction": null,
  "simulated": true,
  "safe_to_display": true
}
MCP smoke: PASS
```

The first launcher attempt exited 1 because the sandbox denied binding
`0.0.0.0:8000` with `[Errno 1] operation not permitted`. The same launcher
passed with local-listener permission. No transport/authentication control
was changed to pass the check.

The API Engineer skill's auxiliary `postman status` command exited 1 with
`error: unknown command 'status'`, as already observed in Stage 01. No Postman
workspace/setup was used or modified; the executable MCP contract is validated
with the official SDK and pytest.

## Touched files

- `.env.example`: optional persistent database path.
- `README.md`: Stage 02 contract, configuration, routing, persistence, and limits.
- `pyproject.toml`: project description.
- `configs/global.yaml`: two bilingual route groups.
- `configs/workflows/buy_package.v1.yaml`: purchase entry state and A/B catalog.
- `configs/workflows/send_credit.v1.yaml`: transfer entry state.
- `src/csol/__init__.py`: package description.
- `src/csol/config.py`: normalization, safe YAML loading, strict validation.
- `src/csol/controller.py`: entry routing, active-state handling, cancel, replies.
- `src/csol/models.py`: saved-state response contract and supported entry states.
- `src/csol/router.py`: exact normalized phrase/word-boundary matching.
- `src/csol/server.py`: controller integration and configurable SQLite path.
- `src/csol/store.py`: five tables, sessions, SQL transactions, minimal audit.
- `scripts/mcp_smoke.py`: persisted-state contract and fresh synthetic references.
- `tests/conftest.py`: isolated temporary controller fixture.
- `tests/test_config.py`: preserve Stage 00 fixture test and verify configuration.
- `tests/test_controller.py`: active states, restart, cancel, audit, rollback.
- `tests/test_mcp_server.py`: preserve transport guarantees and verify persistence.
- `tests/test_routing.py`: four routing tests with 31 parameterized cases.
- `tests/test_store.py`: persistent schema and unique-key checks.
- `docs/stage_02_verification.md`: this report.

Synthetic session IDs remain untrusted identity references; distinct saved
sessions do not prove customer ownership. Model-mediated tool use and final
Hermes reply fidelity are not enforced by MCP. No Hermes configuration/source,
Docker deployment, later-stage FSM, or production integration was changed.
Stage 02 stops here for review.
