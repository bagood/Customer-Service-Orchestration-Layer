# Stage 03 verification

Verified November 8, 2026, using the existing CPython 3.12.13 environment and
official MCP SDK 1.30.0. Commands below run from
`customer-service-orchestration-layer/`. No dependency pins changed.

## Implemented scope

The controller implements the fixed A/B catalog and the purchase sequence:

```text
SELECT_PACKAGE -> ENTER_BALANCE -> CONFIRM_PURCHASE
  -> [EXECUTE_PURCHASE, internal only] -> FEEDBACK
```

Selections are whole normalized A/B/1/2 tokens, accepted only at selection.
Balances are raw nonnegative ASCII integer strings in IDR. They are typed
simulation values, never operator-verified balances. Insufficient input keeps
the package and balance-entry state; equal-to-price input is sufficient.
Only an entire normalized `yes` or `ya` authorizes the controller's next
transition; exact `no` or `tidak` clears the workflow without execution.

The controller revalidates the saved state, package and sufficient balance
before obtaining a uniquely keyed transaction record. Only this controller
calls the private deterministic `_mock_buy_package` function. It records
`SUCCEEDED`, reads the receipt, and then constructs the canonical demo success
reply. The transaction ID is the existing SQLite integer primary key.
Transactions, final session state and audit event commit atomically before
the response is returned. No schema migration is required.

Internal execution has revision 4 on a fresh successful journey; feedback
has revision 5. Execution is transient controller state within that turn,
never an input action, exported MCP tool, returned state, or separately
committed session. The audit event records confirmation directly to feedback.

Exceptions, timeouts and invalid mock receipts record `UNKNOWN`. An existing
non-success record is held without another mock call or success claim. The
generic MCP unavailable reply reports an unconfirmed outcome and prohibits
automatic retry rather than asserting no execution occurred. This narrow
guard does not implement Stage 05 message replay caching, crash recovery,
ownership checks or concurrency verification.

## Commands and results

```text
$ .venv/bin/python -m pytest -q
280 passed, 1 warning in 1.59s

$ .venv/bin/python -m pip check
No broken requirements found.

$ git diff --check
(exit 0, no output)

$ postman status
error: unknown command 'status'
(exit 1)
```

The unchanged Stage 02 baseline first passed 167 tests. An intermediate run
passed 270 tests before the additional MCP integration and invalid-receipt
checks; the final run above passed all 280. No pytest run failed.
The warning remains Starlette's existing HTTPX test-client deprecation notice.
`pip check` also disabled its unwritable cache but exited zero.

The API Engineer skill's auxiliary `postman status` check encounters the same
unsupported command already recorded in Stages 01 and 02. No Postman workspace
or setup was used or changed. The executable MCP contract is validated by the
official Python SDK and pytest; no control was weakened for this CLI gap.

## Acceptance gate and evidence

| Gate | Passing tests and observed behavior |
| --- | --- |
| Invalid C/empty selection | `test_invalid_selection_and_skipped_states_never_execute`, `test_empty_selection_is_rejected_before_mutation`: C holds selection; empty input fails strict validation; zero mock calls/records |
| B + 15000 | `test_insufficient_balance_preserves_b_and_can_be_retried`: saved B remains at `ENTER_BALANCE`; zero mock calls/records |
| B + 20000 | `test_equal_price_is_sufficient_but_never_executes_before_yes`: sufficient balance advances to confirmation; zero mock calls/records |
| B + 25000 + exact yes | `test_exact_confirmation_records_one_succeeded_transaction`: one `SUCCEEDED` record, canonical demo reply, feedback state |
| Exact no/tidak | `test_exact_negative_cancels_without_execution`: idle state, cleared data, zero mock calls/records |
| Injected confirmation | `test_confirmation_requires_an_entire_affirmative_token`: saved confirmation state, zero mock calls/records |
| Skip required states | Selection/balance invalid-input tests and `test_saved_prerequisites_are_rechecked_before_execution`: no execution, including missing/invalid package or insufficient saved balance |
| Persist before success wording | `test_success_reply_requires_persisted_success_status`: suppressing the status write prevents the success response and rolls back the turn |
| No blind retry on unknown/timeout | `test_mock_failure_records_unknown_and_blocks_reexecution`, `test_invalid_mock_receipts_never_generate_success`, `test_existing_non_success_outcomes_are_never_blindly_retried` |
| Restart and repeated confirmation | `test_purchase_progress_and_feedback_survive_restart_without_reexecuting`, `test_mcp_purchase_resumes_confirmation_after_app_restart`: retain receipt and one record |
| Private execution surface | Existing single-tool discovery and expanded unknown-tool tests reject mock/backend/execution tool names; discovery excludes internal execution from returned states |
| MCP journey | `test_official_mcp_client_completes_package_b_purchase`: authenticated official client initialization, discovery and eight turns over real ASGI Streamable HTTP, validating output schemas and SQLite outcomes |

Earlier routing, authentication, input/output, transport-security, audit and
rollback checks remain passing. The earlier active-state test now uses invalid
C instead of A because A is intentionally a valid Stage 03 selection. Its
global-rerouting assertions remain. Configuration tests now expect the exact
purchase sequence and additionally reject changes to fixed demo prices.

## Complete Package B trace

Observed using the reproduction below, exit zero:

```text
'buy package' -> SELECT_PACKAGE v1; transactions=0; data={}
'B' -> ENTER_BALANCE v2; transactions=0; data={"package":"B"}
'15000' -> ENTER_BALANCE v2; transactions=0; data={"package":"B"}
'25000' -> CONFIRM_PURCHASE v3; transactions=0; data={"package":"B","balance_idr":25000}
'yes' -> FEEDBACK v5; transactions=1; data={"package":"B","balance_idr":25000,"transaction_id":1}
Demo purchase SUCCEEDED: Package B (Rp 20,000), transaction 1. Simulation only; no real purchase or operator balance verification. Please rate this demo from 1 to 5. Feedback collection is not available yet. Type cancel or batal to return to the menu.
transactions=[{"id": 1, "idempotency_key": "buy_package:demo-stage03-b:1:3", "status": "SUCCEEDED"}]
```

The final turn includes internal `EXECUTE_PURCHASE v4` before `FEEDBACK v5`.
Its one audit event is `purchase_succeeded`, from `CONFIRM_PURCHASE` to `FEEDBACK`.
The earlier events are `workflow_started`, `package_selected`,
`insufficient_balance`, and `balance_accepted`. There are five audit rows;
feedback and processed-message tables remain empty.

Reproduce with a fresh temporary SQLite file:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from csol.config import load_configuration
from csol.controller import Controller
from csol.models import TurnInput
from csol.store import Store

with TemporaryDirectory(prefix='csol-stage03-trace-') as directory:
    controller = Controller(Store(Path(directory) / 'trace.sqlite3'), load_configuration())
    for index, message in enumerate(('buy package', 'B', '15000', '25000', 'yes'), start=1):
        response = controller.process_turn(TurnInput(
            session_ref='demo-stage03-b', message_id=f'trace-{index}', message=message,
        ))
        with controller.store.transaction() as connection:
            row = connection.execute('SELECT * FROM sessions').fetchone()
            count = connection.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
        print(f'{message!r} -> {response.state} v{response.state_version}; transactions={count}; data={row["data_json"]}')
    print(response.customer_reply)
    with controller.store.transaction() as connection:
        print('transactions=' + json.dumps([dict(row) for row in connection.execute('SELECT * FROM transactions')]))
        print('audit=' + json.dumps([dict(row) for row in connection.execute('SELECT event_type, from_state, to_state, state_version FROM audit_events ORDER BY id')]))
PY
```

## Touched files

- `README.md`: current contract, purchase journey, storage behavior and limits.
- `configs/workflows/buy_package.v1.yaml`: full Python-enforced purchase sequence.
- `src/csol/config.py`: exact sequence and fixed catalog validation.
- `src/csol/controller.py`: purchase FSM, typed-input checks, exact confirmation,
  private execution, recorded-success replies and feedback prompt.
- `src/csol/mock_transactions.py` (new): private deterministic purchase mock.
- `src/csol/models.py`: states, strict saved purchase data and success receipt.
- `src/csol/server.py`: Stage 03 tool description/version and unconfirmed-outcome
  error reply; the single-tool surface and authentication remain.
- `src/csol/store.py`: obtain/read/finalize transaction records in the existing schema.
- `tests/test_config.py`: full sequence and immutable demo-price expectations.
- `tests/test_controller.py`: use C for the now-invalid package-selection case.
- `tests/test_mcp_server.py`: private-tool rejection, output schema, safe errors,
  official-client purchase journey and restart/invalid-prerequisite checks.
- `tests/test_purchase.py` (new): Stage 03 gates and purchase safety tests.
- `docs/stage_03_verification.md` (new): this report and reproducible trace.

## Stage boundary

Credit transfer remains at its Stage 02 placeholder. Feedback is requested but
not collected; a feedback turn holds its state and cannot purchase again.
Existing explicit cancel/batal returns to the menu. No live balances, real
telecom or Hermes calls, customer PII, LLMs, external backend requests, Docker
changes, Hermes configuration/source changes, dynamic policies, or standalone
transaction APIs were added. The MCP integration evidence is offline ASGI,
not a deployed Hermes or Docker check. Synthetic session references remain
unauthenticated customer identity. Stage 03 stops here for review.
