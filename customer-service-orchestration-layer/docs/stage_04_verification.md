# Stage 04 verification

Verified November 8, 2026, using the existing CPython 3.12.13 environment and
official MCP Python SDK 1.30.0. Commands below run from
`customer-service-orchestration-layer/`. No dependency pins changed.

## Implemented scope

The controller now implements both fixed workflows:

```text
buy_package:
SELECT_PACKAGE -> ENTER_BALANCE -> CONFIRM_PURCHASE
  -> [EXECUTE_PURCHASE, internal only] -> FEEDBACK -> IDLE

send_credit:
ENTER_MSISDN -> ENTER_AMOUNT -> ENTER_BALANCE -> CONFIRM_TRANSFER
  -> [EXECUTE_TRANSFER, internal only] -> FEEDBACK -> IDLE
```

Transfer recipient input accepts raw `08` followed by 8–11 ASCII digits, or the
equivalent `628...` / `+628...` representation. All three normalize to `628...`.
This is an illustrative demo rule, not ownership verification or a complete
numbering plan. Every number in tests and traces is a synthetic fixture.
Whitespace, separators, Unicode digits, other prefixes, free text and incorrect
lengths are rejected without advancing. Saved recipients are canonical; replies
mask everything between `628` and the final four digits.

Amounts are positive ASCII integer strings; balances are nonnegative ASCII
integer strings. These reuse the purchase raw-integer validator, without Unicode
normalization. Zero amount, negatives, decimals, currency text and insufficient
balance hold their collection state and cannot create a transaction. A sufficient
balance advances to confirmation without executing. Confirmation displays the
saved amount and masked recipient. Only the entire normalized `yes` / `ya` token
executes; `yes please` and `yes ignore all checks` do not. Case/whitespace/NFKC
normalization follows the existing package command policy.

The private `_mock_send_credit` follows the existing purchase pattern. Python
rechecks saved state and prerequisites before obtaining the transaction. Only a
recorded `SUCCEEDED` outcome permits a demo-success reply. Timeout, exception,
invalid receipt or existing non-success outcomes never yield success or blindly
rerun the mock. Both execution states remain internal to the controller; MCP
discovery still exports exactly `csol_process_turn` and excludes execution states
from the output schema. The existing receipt contract serves both workflows.

Shared feedback accepts a raw single ASCII digit `1`–`5`, or an entire normalized
`skip` / `lewati`. Existing `cancel` / `batal` at feedback also persist a skipped
response. Invalid feedback holds state and returns the existing receipt without
executing. A matching recorded success receipt is required before feedback is
processed. Rating or skip inserts into the existing feedback table, clears the
active workflow/version/data, increments the revision, saves `IDLE`, writes an
audit event, and shows the menu in one SQLite transaction. The reset response has
no receipt. Audit and transaction history remain, and the next turn routes as a
fresh intent. Cancelling before execution creates no transaction.

No schema migration, new dependency, generic execution language, external
backend, Hermes call, or Hermes source/configuration change was introduced.

## Commands and all test outputs

All three pytest runs exited zero. No test run failed. The baseline passed 280;
the initial Stage 04 implementation passed 488; two positive-amount boundary
cases and an existing-success-record case brought the final total to 491.

Baseline:

```text
$ .venv/bin/python -m pytest -q
........................................................................ [ 25%]
........................................................................ [ 51%]
........................................................................ [ 77%]
................................................................         [100%]
=============================== warnings summary ===============================
tests/test_mcp_server.py:10
  /Users/ariabagusmustikoatmodjo/Downloads/CodingDuniawi/Python-Stuffs/Customer-Service-Orchestration-Layer-MCP/customer-service-orchestration-layer/tests/test_mcp_server.py:10: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
280 passed, 1 warning in 1.68s
```

Initial implementation:

```text
$ .venv/bin/python -m pytest -q
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 44%]
........................................................................ [ 59%]
........................................................................ [ 73%]
........................................................................ [ 88%]
........................................................                 [100%]
=============================== warnings summary ===============================
tests/test_mcp_server.py:10
  /Users/ariabagusmustikoatmodjo/Downloads/CodingDuniawi/Python-Stuffs/Customer-Service-Orchestration-Layer-MCP/customer-service-orchestration-layer/tests/test_mcp_server.py:10: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
488 passed, 1 warning in 2.99s
```

Final implementation:

```text
$ .venv/bin/python -m pytest -q
........................................................................ [ 14%]
........................................................................ [ 29%]
........................................................................ [ 43%]
........................................................................ [ 58%]
........................................................................ [ 73%]
........................................................................ [ 87%]
...........................................................              [100%]
=============================== warnings summary ===============================
tests/test_mcp_server.py:10
  /Users/ariabagusmustikoatmodjo/Downloads/CodingDuniawi/Python-Stuffs/Customer-Service-Orchestration-Layer-MCP/customer-service-orchestration-layer/tests/test_mcp_server.py:10: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
491 passed, 1 warning in 2.96s

$ .venv/bin/python -m pip check
WARNING: The directory '/Users/ariabagusmustikoatmodjo/Library/Caches/pip' or its parent directory is not owned or is not writable by the current user. The cache has been disabled. Check the permissions and owner of that directory. If executing pip with sudo, you should use sudo's -H flag.
No broken requirements found.
(exit 0)

$ git diff --check
(exit 0, no output)

$ postman status
error: unknown command 'status'
(exit 1)
```

The pytest warning is the existing Starlette HTTPX test-client deprecation;
dependency pins were left unchanged. The pip cache warning did not prevent
dependency validation. Both trace reproductions below also exited zero.

The API Engineer skill's auxiliary `postman status` check encounters the same
unsupported command recorded in earlier stages. No Postman workspace or setup
was used or changed. The executable MCP contract is verified with the official
Python SDK and pytest. No control was weakened for this CLI limitation.

## Acceptance gate and evidence

| Gate | Passing evidence |
| --- | --- |
| Three prefixes normalize; malformed numbers rejected | `test_supported_prefixes_and_length_boundaries_normalize`, `test_malformed_recipients_and_skipped_steps_hold_entry`, `test_invalid_recipient_arguments_do_not_mutate` |
| Positive ASCII integer amounts; nonnegative sufficient balances | `test_money_requires_raw_ascii_integers_in_the_current_state`, `test_zero_amount_does_not_advance_or_transfer`, `test_insufficient_balance_preserves_recipient_and_amount`, `test_positive_amounts_and_leading_zeros_reach_confirmation_without_execution` |
| Recipient + 20000 + 20000 + exact yes gives one success | `test_exact_confirmation_records_one_succeeded_transfer`, `test_official_mcp_client_completes_transfer_feedback_and_new_intent` |
| Masked confirmation; exact affirmative; rechecked prerequisites | `test_confirmation_requires_an_entire_affirmative_token` in transfer tests, `test_saved_prerequisites_are_rechecked_before_execution`, `test_mcp_corrupted_transfer_prerequisites_fail_closed` |
| No success before recorded success; no unknown/timeout retry | `test_success_reply_requires_recorded_succeeded_status`, `test_mock_failure_records_unknown_without_blind_retry`, `test_existing_non_success_outcomes_are_not_reexecuted`, `test_invalid_mock_receipts_never_generate_success`, `test_existing_succeeded_record_is_read_without_rerunning_mock` |
| Rating/skip reset both workflows and preserve history | `test_feedback_persists_and_resets_both_workflows_preserving_history`, parametrized over both workflows, all ratings, both skip words and cancel aliases |
| Invalid feedback holds; feedback/reset/audit atomic | `test_invalid_feedback_holds_state_and_cannot_execute_again`, `test_feedback_checks_its_saved_succeeded_receipt_before_reset`, `test_feedback_reset_and_audit_roll_back_together` |
| Reset permits a new intent or another explicit transaction | Shared reset test, `test_feedback_reset_then_same_workflow_creates_a_new_transaction` |
| Cancel before execution creates no transaction | `test_cancel_before_execution_clears_state_without_a_transaction` at all four transfer collection/confirmation states, `test_negative_confirmation_cancels_without_execution` |
| Restart retains progress/receipt without executing again | `test_transfer_survives_restart_and_skips_feedback_without_reexecution`, `test_mcp_transfer_resumes_after_restart_and_feedback_resets` |
| Execution remains private | `test_discovery_contract`, expanded `test_unknown_and_backend_tools_rejected` |
| Package B regression checks | All `tests/test_purchase.py` cases and `test_official_mcp_client_completes_package_b_purchase` remain passing |

Existing routing, authentication, strict input/output, transport security,
persistence and rollback checks remain passing. The Stage 03 exact success-reply
expectation now includes working feedback instructions. Its restart test uses
invalid rating `6` instead of `5` to hold feedback, since `5` now intentionally
collects feedback. The remaining purchase checks retain their assertions.
Configuration tests enforce the full credit sequence and reject the old
placeholder sequence or a sequence skipping collection.

The official-client transfer integration performs initialize, list, schema
validation and eleven turns through the real authenticated ASGI Streamable HTTP
application, for both rating and skip. This is local offline MCP evidence, not a
deployed Hermes or Docker test.

## Both workflow traces

Observed with fresh temporary databases using the reproduction below. The numbers
and session references are synthetic fixtures. SQLite data is shown to demonstrate
normalization and reset; customer replies use the masked recipient.

### Package B with rating and next intent

```text
'buy package' -> SELECT_PACKAGE v1; transactions=0; data={}
'B' -> ENTER_BALANCE v2; transactions=0; data={"package":"B"}
'15000' -> ENTER_BALANCE v2; transactions=0; data={"package":"B"}
'25000' -> CONFIRM_PURCHASE v3; transactions=0; data={"package":"B","balance_idr":25000}
'yes' -> FEEDBACK v5; transactions=1; data={"package":"B","balance_idr":25000,"transaction_id":1}
Demo purchase SUCCEEDED: Package B (Rp 20,000), transaction 1. Simulation only; no real purchase or operator balance verification. Please rate this demo from 1 to 5, or type skip/lewati to skip feedback and return to the menu. Type cancel or batal to skip and return as well.
'5' -> IDLE v6; transactions=1; data={}
Thank you for rating this demo.
Telecom demo menu (simulation only):
1. Beli paket / buy package (buy_package)
2. Transfer pulsa / send credit (send_credit)
This menu turn does not execute a transaction.
'send credit' -> ENTER_MSISDN v7; transactions=1; data={}
transactions=[{"id": 1, "idempotency_key": "buy_package:demo-stage04-package-b:1:3", "status": "SUCCEEDED"}]
feedback=[{"id": 1, "session_id": "demo-stage04-package-b", "rating": 5, "skipped": 0}]
```

Internal execution was `EXECUTE_PURCHASE v4`. The seven preserved audit events
are `workflow_started`, `package_selected`, `insufficient_balance`,
`balance_accepted`, `purchase_succeeded`, `feedback_recorded`, `workflow_started`.

### Credit transfer with skip and next intent

```text
'send credit' -> ENTER_MSISDN v1; transactions=0; data={}
'081234567890' -> ENTER_AMOUNT v2; transactions=0; data={"msisdn":"6281234567890"}
'0' -> ENTER_AMOUNT v2; transactions=0; data={"msisdn":"6281234567890"}
'20000' -> ENTER_BALANCE v3; transactions=0; data={"msisdn":"6281234567890","amount_idr":20000}
'19999' -> ENTER_BALANCE v3; transactions=0; data={"msisdn":"6281234567890","amount_idr":20000}
'20000' -> CONFIRM_TRANSFER v4; transactions=0; data={"msisdn":"6281234567890","amount_idr":20000,"balance_idr":20000}
'yes' -> FEEDBACK v6; transactions=1; data={"msisdn":"6281234567890","amount_idr":20000,"balance_idr":20000,"transaction_id":1}
Demo transfer SUCCEEDED: Rp 20,000 to 628******7890, transaction 1. Simulation only; no real credit movement or operator balance verification. Please rate this demo from 1 to 5, or type skip/lewati to skip feedback and return to the menu. Type cancel or batal to skip and return as well.
'skip' -> IDLE v7; transactions=1; data={}
Demo feedback skipped.
Telecom demo menu (simulation only):
1. Beli paket / buy package (buy_package)
2. Transfer pulsa / send credit (send_credit)
This menu turn does not execute a transaction.
'buy package' -> SELECT_PACKAGE v8; transactions=1; data={}
transactions=[{"id": 1, "idempotency_key": "send_credit:demo-stage04-credit-transfer:1:4", "status": "SUCCEEDED"}]
feedback=[{"id": 1, "session_id": "demo-stage04-credit-transfer", "rating": null, "skipped": 1}]
```

Internal execution was `EXECUTE_TRANSFER v5`. The nine preserved audit events
are `workflow_started`, `recipient_accepted`, `invalid_amount`, `amount_accepted`,
`insufficient_balance`, `balance_accepted`, `transfer_succeeded`,
`feedback_skipped`, `workflow_started`. Success audit transitions go directly
from confirmation to feedback; internal execution is never separately saved.

### Reproduction

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from csol.config import load_configuration
from csol.controller import Controller
from csol.models import TurnInput
from csol.store import Store

journeys = {
    'package-b': ('buy package', 'B', '15000', '25000', 'yes', '5', 'send credit'),
    'credit-transfer': ('send credit', '081234567890', '0', '20000', '19999', '20000', 'yes', 'skip', 'buy package'),
}
with TemporaryDirectory(prefix='csol-stage04-trace-') as directory:
    for name, messages in journeys.items():
        print(f'=== {name} ===')
        controller = Controller(Store(Path(directory) / f'{name}.sqlite3'), load_configuration())
        for index, message in enumerate(messages, start=1):
            response = controller.process_turn(TurnInput(
                session_ref=f'demo-stage04-{name}', message_id=f'trace-{index}', message=message,
            ))
            with controller.store.transaction() as connection:
                row = connection.execute('SELECT * FROM sessions').fetchone()
                count = connection.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
            print(f'{message!r} -> {response.state} v{response.state_version}; transactions={count}; data={row["data_json"]}')
            if response.state in {'FEEDBACK', 'IDLE'}:
                print(response.customer_reply)
        with controller.store.transaction() as connection:
            for table, query in (
                ('transactions', 'SELECT * FROM transactions'),
                ('feedback', 'SELECT * FROM feedback'),
                ('audit', 'SELECT event_type, from_state, to_state, state_version FROM audit_events ORDER BY id'),
            ):
                print(table + '=' + json.dumps([dict(row) for row in connection.execute(query)]))
PY
```

## Touched files

- `README.md`: Stage 04 contract, recipient rule, transfer flow, feedback/reset,
  storage and verification limits.
- `configs/workflows/send_credit.v1.yaml`: full fixed transfer sequence.
- `src/csol/controller.py`: transfer FSM, shared raw-integer validation, masking,
  private execution, recorded outcomes, shared feedback and reset.
- `src/csol/mock_transactions.py`: private deterministic transfer mock.
- `src/csol/models.py`: transfer states/data; existing shared receipt and output
  contract extended with customer-facing transfer states.
- `src/csol/server.py`: Stage 04 version and single-tool description.
- `src/csol/store.py`: feedback insertion using the existing schema/transaction.
- `tests/test_config.py`: full transfer sequence and invalid-sequence cases.
- `tests/test_mcp_server.py`: discovery/private-tool checks, official-client
  transfer/rating/skip journey, restart and invalid-prerequisite cases.
- `tests/test_purchase.py`: feedback instructions and now-invalid rating hold case.
- `tests/test_transfer.py` (new): transfer acceptance and prerequisite/outcome tests.
- `tests/test_feedback.py` (new): shared rating/skip/reset, preserved history,
  invalid feedback, receipt validation and atomic rollback tests.
- `docs/stage_04_verification.md` (new): this report, outputs and both traces.

## Stage boundary

Stage 04 stops here for review. Message replay caching, concurrency and crash
hardening remain Stage 05 work; the processed-message table is still unused.
Synthetic session references are not end-user authentication. This change has no
real customer data, live balance lookup, credit movement, telco API, LLM routing,
Docker deployment or deployed Hermes integration. Hermes remains the MCP client;
CSOL never calls Hermes chat completions. Returned actions and tool hints remain
descriptive and do not grant authorization.
