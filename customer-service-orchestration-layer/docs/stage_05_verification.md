# Stage 05 verification

Verified November 8, 2026 with the existing CPython 3.12.13 environment and
MCP Python SDK 1.30.0. Commands run from `customer-service-orchestration-layer/`.
No dependencies changed. Stage 05 ends here for review; Docker and deployed
Hermes integration remain outside this change.

## Safety checklist and passing proof

Unauthorized mock invocations under CSOL's saved-state/action rules: **0**.
Duplicate mock invocations for one persisted operation: **0**. These are FSM
and idempotency claims for synthetic fixtures, not customer-identity claims.

| Check | Exact passing tests |
| --- | --- |
| English/Indonesian fake authority, fake tool results and skipped confirmation cannot invoke either mock | `tests/test_hardening.py::test_fake_authority_and_tool_output_never_authorize_execution` (both workflows, every collection/confirmation state) |
| Extra permissions/state/version/outcome fields, oversized text and malformed arguments mutate no table | `tests/test_mcp_server.py::test_mcp_state_jump_and_invalid_arguments_do_not_mutate_active_session`, `test_invalid_tool_arguments_are_safe_errors` |
| Wrong service token cannot confirm a saved operation or mutate any table | `tests/test_mcp_server.py::test_mcp_invalid_token_cannot_confirm_an_existing_session`, `test_missing_or_invalid_auth_rejects_before_dispatch` |
| Replayed session/message pairs return the original response without changing sessions, transactions, feedback, audit or cache, including after restart and later workflows | `tests/test_hardening.py::test_replay_returns_original_response_without_mutating_any_table`, `test_same_message_id_has_independent_session_scope` |
| Parallel confirmations execute once and share one successful transaction ID; new message IDs cannot bypass the persisted key | `tests/test_hardening.py::test_parallel_confirmations_execute_exactly_one_saved_operation` (same and distinct message IDs), `test_simultaneous_new_confirmation_ids_share_persisted_key` |
| Saved prerequisites are re-read immediately before each private call; stale writes and impossible revisions fail closed | `tests/test_hardening.py::test_execution_rechecks_saved_prerequisites_immediately_before_mock`, `test_stale_version_write_is_rejected_without_mutation`, `test_invalid_saved_revision_fails_closed_without_mutation`; existing `test_saved_prerequisites_are_rechecked_before_execution` in both purchase and transfer modules |
| FAILED, UNKNOWN and timeout never claim success or blindly retry, even after restart with the default successful mock | `tests/test_hardening.py::test_deterministic_non_success_outcomes_never_claim_success_or_retry`, `tests/test_mcp_server.py::test_mcp_timeout_and_replay_remain_held_after_restart` |
| Crash before/during invocation or final audit/cache failure preserves a durable PENDING fence and blocks retries | `tests/test_hardening.py::test_durable_pending_survives_crash_or_final_commit_failure`, `tests/test_mcp_server.py::test_mcp_final_commit_failure_preserves_pending_fence` |
| Repeat during the reservation gap preserves its pending reply without execution | `tests/test_hardening.py::test_duplicate_in_reservation_gap_preserves_pending_reply_without_invocation` |
| Only a saved SUCCEEDED result permits a success receipt, including cached responses | `tests/test_hardening.py::test_cached_success_is_revalidated_against_ledger`, `test_transaction_statuses_and_terminal_updates_are_fail_closed`, `test_unsupported_persisted_transaction_status_fails_closed`; existing `test_success_reply_requires_persisted_success_status` and `test_success_reply_requires_recorded_succeeded_status` |
| Money parsing is bounded and rejects oversized values in the current state | `tests/test_hardening.py::test_oversized_money_is_rejected_by_state_validation`, `test_transfer_amount_limit_holds_collection_state`, `test_maximum_demo_money_value_can_complete_both_workflows` |
| Logs retain fixed codes/transitions without customer values or identifiers | `tests/test_hardening.py::test_state_transition_logs_redact_customer_values`, `tests/test_mcp_server.py::test_security_error_logs_contain_fixed_codes_without_input` |
| Stage 04 databases and the original happy paths still work | `tests/test_hardening.py::test_existing_stage04_database_supports_hardened_turns_without_rebuild`; existing `tests/test_mcp_server.py::test_official_mcp_client_completes_package_b_purchase`, `test_official_mcp_client_completes_transfer_feedback_and_new_intent`, plus all earlier tests |
| Customer identity binding is explicitly absent | `tests/test_mcp_server.py::test_shared_service_token_does_not_bind_synthetic_sessions_to_customers` proves an unknown reference cannot reuse another row's prerequisites, but a separate service-authenticated client knowing the existing reference **can** confirm it |

Unqualified test names in each cell belong to the most recently named module
in that cell. All two-workflow hardening checks use synthetic sessions/numbers.
The MCP tests use real ASGI transport; existing full journeys additionally use
the official MCP client. No deployed Hermes or live telecom service was tested.

## Implementation and recovery policy

The public contract remains exactly one tool:
`csol_process_turn(session_ref, message_id, message)`. Unexpected fields remain
forbidden. State, permissions, transaction data and test outcomes cannot be
supplied as tool arguments. No new tools, network dependency or Hermes change
was introduced. Replies remain fixed controller templates; text is validated
by the saved workflow state, without an injection blacklist.

Every valid completed turn records its validated response under the existing
SQLite `(session_id, message_id)` primary key, together with its session and
audit writes. Reusing the pair returns that original response even if the new
text differs or the workflow has moved on. Each distinct turn must have a fresh
ID. Raw messages are not persisted; synthetic message IDs are persisted as cache
keys and excluded from audit/runtime logs. Cached success receipts are checked
against the ledger before replay.

Mutations acquire `BEGIN IMMEDIATE`; writes compare the expected state revision.
SQLite waits at most one second for locks, with no application retry loop.
Unique transaction keys derive from the saved workflow, synthetic session,
workflow version and confirmation revision, independently of caller message IDs.

A valid exact confirmation first commits a `PENDING` transaction reservation.
The controller reacquires the write lock, reloads/revalidates prerequisites and
checks for a concurrent replay before invocation. Only the request that created
the durable reservation can invoke the private mock. The immediate local mock
runs under the second short write transaction; status, session, response cache
and audit finalize atomically. Existing success rows are read, never reexecuted.
Execution states remain internal and absent from the public response schema.

The deterministic test switch is the private in-process constructor keyword
`_test_mock_outcome`, with `SUCCEEDED` (default), `FAILED`, `UNKNOWN` or `TIMEOUT`.
It feeds a private mock keyword; no environment variable or wire argument
exposes it. Timeout is immediate and deterministic, with no sleep or network call.
Malformed receipts and exceptions produce `UNKNOWN`; known failure produces
`FAILED`. Fresh databases constrain all four ledger statuses; Python enforces
the same rules on older schemas without rebuilding tables.

`PENDING` and `UNKNOWN` hold the saved confirmation state for manual review,
return no actions/receipt, and block yes, no, cancel and new-intent attempts.
They never return success wording or automatically invoke the mock again.
`FAILED` cannot retry that operation, but permits an explicit cancellation.
No reconciliation or manual-resolution tool is provided in this demo.

A crash or final persistence failure can leave `PENDING` even if the local mock
returned success. This intentionally sacrifices automatic completion to retain
the invocation fence. A duplicate arriving in the reservation/reacquisition gap
can record a pending response first; the reserving request then preserves that
reply without invoking the mock. This interleaving also requires review. There
is no background retry or attempt to infer that a pending operation was unused.
This policy is for immediate local simulations; it does not establish safe
execution of real network financial operations.

Money inputs are limited to 10 raw ASCII digits, at most Rp 1,000,000,000.
Existing text/identifier/body bounds remain 1000 characters, 128 characters and
16 KiB respectively. Saved money values and state revisions are validated too.
Runtime logs contain fixed error/event codes and transitions, excluding raw
text, session/message IDs, recipients, balances, tokens and exception details.
Persisted audit retains only its previous synthetic reference/state metadata.

## Commands and results

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` (baseline) | Exit 0; 491 passed, 1 warning |
| `.venv/bin/python -m pytest -q --maxfail=3` (first implementation run) | Exit 1; 3 failed, 40 passed, 1 warning; legacy helpers reused message IDs, and an old audit test expected message IDs absent from the entire database |
| `.venv/bin/python -m pytest -q` (after distinct-turn fixture changes) | Exit 1; 2 failed, 489 passed, 1 warning; old rollback expectations required no transaction row after finalization failure |
| `.venv/bin/python -m pytest tests/test_hardening.py -q` (initial focused checks) | Exit 0; 64 passed |
| `.venv/bin/python -m pytest -q` (first full hardening suite) | Exit 0; 579 passed, 1 warning |
| `.venv/bin/python -m pytest -q` (reservation-gap and numeric boundaries added) | Exit 0; 588 passed, 1 warning |
| `.venv/bin/python -m pytest -q` (final, legacy database/status checks added) | Exit 0; **592 passed, 1 warning in 4.04s** |
| `.venv/bin/python -m pip check` | Exit 0; no broken requirements found; pip disabled its unwritable cache |
| `git diff --check` | Exit 0; no whitespace errors |

The existing warning is Starlette's HTTPX test-client deprecation; dependency
pins were preserved. The final suite contains 101 additional cases relative to
the baseline. Legacy tests now use fresh IDs for distinct turns. Their success,
authorization and prerequisite assertions remain; the two persistence-failure
tests now correctly require the durable `PENDING` row. The audit test still
rejects message IDs in audit data but permits them in the replay-cache key.
The API engineering skill was used for contract/verification discipline; no
Postman workspace, collection, simulation or external publication was used.

## Touched files

- `README.md`: current contract, limits, replay/recovery policy and evidence link.
- `src/csol/auth.py`: fixed redacted authentication error log code.
- `src/csol/controller.py`: replay, durable reservation, immediate prerequisite
  recheck, conservative recovery, bounded money, saved revisions and transition logs.
- `src/csol/mock_transactions.py`: deterministic private test outcomes.
- `src/csol/models.py`: terminal mock result and bounded money/status types.
- `src/csol/server.py`: Stage 05 server version and fixed redacted error codes.
- `src/csol/store.py`: immediate locks, version-checked saves, response caching,
  validated terminal updates and status constraint for fresh databases.
- `tests/test_controller.py`: distinct-turn IDs and audit/cache distinction.
- `tests/test_feedback.py`: distinct-turn IDs.
- `tests/test_purchase.py`: distinct-turn IDs, cache count and durable fence expectation.
- `tests/test_transfer.py`: distinct-turn IDs and durable fence expectation.
- `tests/test_mcp_server.py`: existing distinct-turn IDs and new MCP hardening/limit evidence.
- `tests/test_hardening.py` (new): adversarial, replay, concurrency, crash, outcome,
  prerequisite, version, numeric, log and legacy-database checks.
- `docs/stage_05_verification.md` (new): this report.

## Unimplemented production controls

- **Trusted customer identity and session ownership binding:** the shared bearer
  authenticates Hermes as a service. Synthetic session IDs do not authenticate
  customers. The cross-session test deliberately proves this limitation.
- **Outbound reply gating:** MCP cannot force Hermes to call CSOL or display its
  approved reply; `safe_to_display`, tool hints and `allowed_actions` are metadata.
- Real operator identity/recipient ownership, verified balances, credit movement,
  live telecom APIs and real-money reconciliation/manual resolution.
- Multi-worker operation, distributed coordination, production retention/rate
  limiting, TLS deployment and a production gateway.
- Docker connectivity, deployed Hermes integration/configuration and restrictions
  on destructive Hermes built-in tools (later stages).

No LLM classification, RAG, plugins, queues, external financial calls or customer
PII were added. CSOL never calls Hermes `/v1/chat/completions` or modifies Hermes
source code.
