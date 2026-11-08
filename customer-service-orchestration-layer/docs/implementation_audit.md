# Implementation audit against the CSOL MVP development stages

Evaluated **8 November 2026 (Asia/Jakarta)** against
[CSOL_Codex_MVP_Development_Stages.md](../../CSOL_Codex_MVP_Stage_Prompts/CSOL_Codex_MVP_Development_Stages.md).
Source revision: `e3bef64de4756500df2d78a9b11765621ce92f9c`.

**Verdict:** the core simulated MCP server, both workflows, persistence, action
controls, private Docker deployment and working Hermes CLI integration are
implemented and passed fresh verification. A blanket claim that every checklist
item is fully complete would overstate the evidence: Stage 07's real-Hermes
bypass experiments remain incomplete, and the README omits the explicitly
requested complete message-flow description. There is also a stale live-test
description in the deployment runbook.

No missing core workflow implementation was found in the reviewed source and
tests. This is a bounded implementation audit, not proof that all possible
inputs or failures are safe. Runtime code and deployment configuration were
not changed during this audit.

## Findings and remaining work

### 1. Stage 07 bypass evidence uses supplied client text rather than real Hermes behavior

**Priority: medium; evidence gap.** Stage 07 implementation item 4 asks for Hermes
replying without MCP and claiming success despite a FAILED/UNKNOWN result.
The evaluator's [`client_reply` branch](../scripts/evaluate_mvp.py#L167) merely
copies `visible_reply` from the scenario fixture. It does not invoke Hermes or
deliver a result to its model. The three bypass fixtures establish that an
independent client can display arbitrary text without changing CSOL's ledger.
They do not measure whether Hermes actually omits a call or misreports a failed
result.

The [live Hermes test](../tests/test_hermes_integration.py#L51) covers one Package B
journey with an insufficient-balance retry. It has no adversarial journey or
FAILED/UNKNOWN result supplied to the real model. It requires exactly one call
per turn and fails immediately on omission. The existing
[MVP report](../MVP_REPORT.md#L127) accurately discloses these limitations; this
is incomplete experimental coverage, not a fabricated claim in that report.

To close this item, extend the real-Hermes study with adversarial turns and an
isolated, test-only FAILED/UNKNOWN service setup. Record the actual tool calls,
final visible reply, approved reply and ledger for every attempt, including
omissions and mismatches. If the model resists an attempted bypass, report that
observed result; do not manufacture a failure. Retain the controlled fixtures
as separate demonstrations. The Stage 07 acceptance gate allows disclosed
blockers, so the current report can satisfy that qualified gate without proving
real-model adversarial response fidelity.

### 2. The full message path is missing from the README

**Priority: low; documentation omission.** Stage 00 implementation item 2
specifically requires the complete customer-to-reply message flow in README.
The [README introduction](../README.md#L3) describes the components but does not
describe the whole ordered path, including customer-channel ingress and egress.
The architecture is described more fully in MVP_REPORT.md.

Close this item by adding the following flow to README:

`Customer → Hermes channel/gateway → Hermes MCP client → authenticated private /mcp → CSOL router + FSM + SQLite → private mock telecom functions → canonical MCP result → Hermes channel reply`.

### 3. The deployment runbook describes the previous live-test journey

**Priority: low; documentation inconsistency.** The
[runbook](private_docker_hermes.md#L129) describes five messages with balance
`20000` and a `data/stage06-demo-hermes-*.json` trace. The current
[test](../tests/test_hermes_integration.py#L38) uses six messages with `15000`
then `25000`, and defaults to `data/stage07-demo-hermes-*.json`. The test and
MVP_REPORT.md agree; the runbook needs updating. Historical Stage 06 verification
may retain its original five-turn trace as historical evidence.

## Deployment limitations and deliberate exclusions

The customer-service fragment restricts
[`platform_toolsets.cli`](../hermes/customer-service-profile.example.yaml#L5)
only. A real customer channel's toolsets are neither restricted nor verified by
this repository's live test. This satisfies Stage 06's permitted CLI test-profile
scope, but an external customer-channel rollout still needs its own tool-surface
restriction and observed channel trace. The runbook explicitly says so.

The following absences are deliberate MVP boundaries specified in the source
guide, rather than missing Stage 00–07 runtime features:

- Trusted customer identity and session ownership. A bearer-authenticated client
  knowing another synthetic session reference can confirm it; the suite tests
  and documents that limitation.
- Mandatory Hermes tool invocation and a trusted outbound reply gate. Prompt
  instructions, `allowed_actions` and `safe_to_display` do not enforce delivery.
- Live balances, real charging/provisioning/credit transfer, recipient ownership
  checks, customer PII and real telecom integrations.
- A manual-review resolution operation for PENDING/UNKNOWN transactions. The
  implemented demo safely holds these outcomes without automatic retry.
- Production scaling, rate limiting, reconciliation and a separate production
  gateway. The intended runtime is one process with one SQLite file.
- A matched Hermes-only baseline. Stage 07 item 5 expressly permits `baseline
  not measured`; the artifacts consistently use that disclosure. No comparative
  benefit can be inferred from the reported latency or token counters.
- `csol_get_menu`, which is optional. Only `csol_process_turn` is exported.

## Fresh verification

Commands below ran from `customer-service-orchestration-layer/`. All listed
successful commands exited 0. Existing tracked evaluation artifacts were left
unchanged; fresh JSON evidence was written under `/tmp`.

| Check / exact command | Result observed in this audit |
| --- | --- |
| `.venv/bin/python -m pytest -q` | **626 passed, 2 skipped**, 1 existing Starlette/HTTPX deprecation warning, 5.91 s |
| `.venv/bin/python -m pip check` | No broken requirements; nonfatal unwritable pip-cache warning |
| `.venv/bin/python -c 'import csol'` (included in an interpreter/dependency diagnostic) | Import passed; Python **3.12.13** |
| `.venv/bin/python scripts/evaluate_mvp.py --output /tmp/csol-audit-results.json` | **25/25 passed**, 113 MCP tool calls, 16 private mock invocations, **0 unauthorized**, **0 duplicate** |
| `docker ps --format '{{.Names}} {{.Status}}'` | Existing `csol-csol-1` healthy and `hermes-agent` running |
| `docker inspect csol-csol-1 hermes-agent --format '{{.Name}} image={{.Image}} ports={{json .HostConfig.PortBindings}} networks={{json .NetworkSettings.Networks}}'` | CSOL has no host port bindings and only `csol-private`; Hermes retains `agent-network` plus `csol-private` |
| `docker network inspect csol-private --format 'name={{.Name}} internal={{.Internal}} driver={{.Driver}}'` | `internal=true`, `driver=bridge` |
| `docker exec -i --user hermes --workdir /opt/hermes hermes-agent .venv/bin/python - < scripts/hermes_mcp_probe.py` | Actual persisted-token interpolation, missing-secret rejection, discovery, restricted CLI tool surface and authenticated menu call all passed |
| `CSOL_DOCKER_TEST=1 .venv/bin/python -m pytest tests/test_docker_integration.py -q -s` | **1 passed**, 9.07 s; in-network official MCP client, Package B, SQLite checks and container restart |
| `CSOL_HERMES_TEST=1 CSOL_HERMES_TRACE_PATH=/tmp/csol-audit-hermes-trace.json .venv/bin/python -m pytest tests/test_hermes_integration.py -q -s` | **1 passed**, 44.29 s; six real configured model turns, six correlated MCP calls, six exact canonical replies |

The two tests skipped by the default suite were separately executed and passed
above. Initial ordinary-sandbox Docker inspection failed because access to the
daemon socket was denied; approved elevated execution succeeded. No transport
security or authentication check was weakened.

The API Engineer/API Testing skills guided contract and evidence review. Their
final suggested `postman status` check exited 1 with `unknown command 'status'`
in the installed CLI. No Postman setup was needed or relied on; MCP acceptance
evidence came from the pinned official SDK and existing Hermes integration.

Installed dependency versions match the committed pins: MCP 1.30.0, Pydantic
2.14.3, PyYAML 6.0.3, pytest 9.2.0, Starlette 1.10.0, Uvicorn 0.54.0 and HTTPX
0.28.1. Source and live discovery expose only `csol_process_turn`; Hermes offers
`mcp__csol__csol_process_turn` to the tested CLI profile.

Fresh local MCP/ASGI latency was p50 **4.108 ms**, p95 **4.660 ms**, n=113.
Fresh Hermes CLI end-to-end latency was p50 **6530.171 ms**, p95 **9320.853 ms**,
n=6. These measure different scopes and are not a controlled comparison.
Real external customer-channel coverage remains unmeasured.

The live tests added synthetic data to the existing demo SQLite file. The Docker
journey used `demo-docker-e4a8c74821da48ab865bbe147ef1cbd7`, transaction **5**.
The Hermes journey used `demo-hermes-62dda26114d34b3085b411d6afbeb71d`, transaction
**6**, and conversation
`local-9d43a79236a1e013ae0d9cc781c3b1c9516f852d97cf9f148b728bcb285fb125`.

| Exact Hermes customer message | Saved state / revision | Ledger for that journey |
| --- | --- | --- |
| `buy package` | SELECT_PACKAGE / 1 | none |
| `B` | ENTER_BALANCE / 2 | none |
| `15000` | ENTER_BALANCE / 2 | none |
| `25000` | CONFIRM_PURCHASE / 3 | none |
| `yes` | FEEDBACK / 5 | transaction 6 / SUCCEEDED |
| `skip` | IDLE / 6 | transaction 6 retained |

All six final visible replies matched their independently read SQLite-cached
`customer_reply` exactly. These six successful turns do not establish future
model compliance or a channel-level enforcement boundary.

## Requirement-by-requirement implementation matrix

Numbers identify each stage's numbered **Implement** items. PASS means source
implementation and relevant passing evidence were found. GAP identifies an
omission or incomplete evidence. Intermediate-stage restrictions such as
“no workflows yet” are superseded by later stages; they are not requirements
to remove the final implementation. Historical commit/review sequencing was
not independently audited.

### Stage 00 — foundation

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 00.1 Project structure | PASS | All required directories/files exist; package uses `src/csol`, pytest and editable installation. |
| 00.2 Precise message flow in README | GAP | Full ordered customer-to-channel reply path is absent from README; finding 2. |
| 00.3 Non-goals, optional invocation, outbound limit | PASS | README “Verification and limits” explicitly documents them and the simulation-only scope. |
| 00.4 Tested Python/dependency pins and import | PASS | `.python-version`, requirements, pyproject and README; fresh import, version diagnostic and pip check passed. |
| 00.5 Import/config smoke tests; ignore secrets/data | PASS | `test_smoke.py`, `test_config.py`, `.gitignore`; Git tracks only `.env.example` and `data/.gitkeep` for those locations. |

### Stage 01 — authenticated MCP

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 01.1 Port 8000 `/mcp`; approved tool only | PASS | `server.py`, Dockerfile; `test_discovery_contract`, official-client discovery and fresh Hermes probe. |
| 01.2 Strict Pydantic input/output contract | PASS | `models.py`; `test_invalid_tool_arguments_are_safe_errors`, `test_invalid_outputs_fail_closed`, maximum-length tests. |
| 01.3 Fixed safe menu without execution | PASS | `MENU_REPLY`, IDLE unsupported-input path; `test_unsupported_turns_show_menu_and_persist_idle_state`. Routing behavior intentionally evolved in Stage 02. |
| 01.4 Bearer auth before dispatch; Host/Origin policy | PASS | `auth.py`, SDK `TransportSecuritySettings`; missing/invalid/duplicate-header, before-body, bad-host/origin and no-mutation tests. |
| 01.5 Official-client smoke script and commands | PASS | `scripts/mcp_smoke.py`, README/runbook; fresh in-container smoke passed within the Docker integration test. |

### Stage 02 — router and SQLite

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 02.1 Two bilingual route groups; boundaries/ambiguity | PASS | `configs/global.yaml`, `router.py`; all `test_routing.py` cases pass. |
| 02.2 Five persistent tables and required keys | PASS | `store.py` schema; `test_persistent_schema_has_required_tables_and_session_fields`, `test_required_unique_keys_are_enforced_by_sqlite`. |
| 02.3 IDLE-only routing, entry states, cancel | PASS | `Controller.process_turn`, `_cancel`; active-workflow, exact/embedded cancel and separate-session tests. |
| 02.4 Startup-validated versioned YAML, Python transitions | PASS | `config.py`, workflow YAML, `_validate_session`; invalid YAML/catalog/sequence/version tests. |
| 02.5 Canonical saved state/version and redacted audit | PASS | Response creation, `save_session`, `record_event`; atomic rollback, audit-redaction and restart tests. |

### Stage 03 — purchase

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 03.1 A/B prices and A/B/1/2 selection | PASS | Fixed catalog validation and `_purchase_turn`; invalid/empty selection and all alias tests. |
| 03.2 Required FSM; execution private/internal | PASS | `_purchase_turn`, `_execute_purchase`; no transaction tool/action exported; skip-state tests. |
| 03.3 ASCII nonnegative balance, insufficient retry/equality | PASS | `_ascii_integer`, saved purchase data; B + 15000 retry, equal-price and malformed-number tests; fresh live retry trace. |
| 03.4 Exact normalized yes/ya and no/tidak | PASS | Entire-token comparisons; `test_confirmation_requires_an_entire_affirmative_token`, exact negative and injected-confirmation tests. |
| 03.5 Recheck, one transaction, recorded success, feedback | PASS | `_run_reserved_mock`, `_saved_receipt`; success/persisted-prerequisite, no-reexecution and recorded-status tests. |
| 03.6 No LLM/live API/public transaction backend | PASS | Private deterministic Python mock; only the single turn tool is discovered. |

### Stage 04 — transfer and feedback

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 04.1 Required transfer FSM, private execution | PASS | `_transfer_turn`, `_execute_transfer`; complete official-client transfer and skipped-state tests. |
| 04.2 Three prefixes, canonical synthetic MSISDN, documented rule | PASS | Raw full-match normalization to `628...`; prefix and malformed-input tests, README rule. |
| 04.3 Positive ASCII amount and sufficient ASCII balance | PASS | `_ascii_integer`, `TransferData`, state checks; zero/negative/decimal/insufficient/equal-balance tests. |
| 04.4 Masked confirmation, exact yes, prerequisite/result checks | PASS | `_masked_recipient`, `_transfer_prompt`, `_execute_transfer`; confirmation, saved prerequisite and success-status tests. |
| 04.5 Rating/skip persisted, IDLE reset, history and cancel | PASS | `_feedback_turn`, `record_feedback`, `_cancel`; all shared feedback tests, history/reset and next-intent journeys. |
| 04.6 Reuse contracts/store/validators; no generic DSL | PASS | Shared `TurnResponse`, models, SQLite store, numeric validation and feedback handler. |

### Stage 05 — reliability and adversarial controls

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 05.1 Fail-closed saved-state/prerequisite authorization | PASS | `_validate_session`, immediate saved-data re-read; corruption, fake-authority and pre-mock prerequisite tests. |
| 05.2 Persisted message replay and transaction idempotency | PASS | Composite processed-message primary key; transaction key from saved workflow/session/version/revision; replay and restart tests. |
| 05.3 Serialized writes, version checks, parallel confirm | PASS | `BEGIN IMMEDIATE`, optimistic revision predicate, UNIQUE transaction key; same/distinct-ID concurrency tests for both workflows. |
| 05.4 Four statuses, deterministic failure/timeout, no blind retry | PASS | Private test switch, durable PENDING reservation, FAILED/UNKNOWN handling; outcome, crash and final-commit failure tests. |
| 05.5 Bounded strict contracts, normal state validation, redaction | PASS | Text/ID/body/money/revision limits; fixed error codes, deterministic templates; oversized, invalid-state, forbidden-field and log tests. |
| 05.6 English/Indonesian attacks, forged outputs, session limits | PASS | `test_hardening.py`, MCP hardening tests; `test_shared_service_token_does_not_bind_synthetic_sessions_to_customers` explicitly demonstrates absent ownership. |
| 05.7 Small limits and simple local coordination | PASS | 1000-character messages, 128-character IDs, 16 KiB body, 10-digit money capped at 1 billion IDR, 1 s SQLite wait, no automatic financial retries or distributed components. Invalid-input retries remain available. |

### Stage 06 — Docker and existing Hermes

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 06.1 CSOL-only private Compose, one process, SQLite bind | PASS | Dockerfile/compose; fresh opt-in Docker test checks process/user/mount/network/ports and restart persistence. |
| 06.2 Existing Hermes attachment with retained egress | PASS | Network overlay and attach procedure; fresh inspect confirms both networks, live probe reaches private MCP. |
| 06.3 Persisted safe config merge, whitelist/timeouts/header | PASS | MCP example, merge helper and preservation/private-file tests; real Hermes interpolation, discovery and missing-secret checks pass. |
| 06.4 Restricted profile with explicit instruction-only limits | PASS | Customer-service profile plus fresh actual CLI tool-surface check. External customer-channel restriction remains a deployment follow-up. |
| 06.5 In-network official-client smoke, real Package B, logs/ledger | PASS | Fresh Docker test and six-turn configured Hermes CLI test passed; calls correlated with SQLite cache and session/ledger rows. Gateway log tool presence is separately checked. |
| 06.6 Pinned compatibility/reload evidence, private endpoint | PASS | Stage 06 verification documents image/releases/SDKs and restart behavior; fresh probe works against the existing deployment with no published CSOL port. |

### Stage 07 — evaluation and decision

| Item | Status | Implementation / evidence |
| --- | --- | --- |
| 07.1 Simple runner with 15+ required synthetic cases | PASS | `scripts/evaluate_mvp.py`, 25 cases in `evaluation/scenarios.json`, reusable pytest cases. All listed required scenario types are present. |
| 07.2 Expected/actual outcomes, counts, reasons, latency/redaction | PASS | Generated per-step evidence; 113 tool calls and 16 instrumented private invocations. Tests also prove deliberately wrong expectations/unauthorized/duplicate calls are detected. |
| 07.3 Real configured Hermes study, correlated calls/reply fidelity | PASS for CLI scope | Fresh six-turn CLI study: 6/6 calls correlated, 6/6 exact replies. External customer-channel coverage is expressly unmeasurable in current artifacts. |
| 07.4 Critical real-Hermes bypass cases and production block | GAP / partial evidence | Three controlled output fixtures and production block are present; actual model omission/false-success experiments are absent. See finding 1. |
| 07.5 Comparable baseline or explicit nonmeasurement | PASS by permitted disclosure | All artifacts say `baseline not measured`; no matched comparison or gains are claimed. |
| 07.6 MVP report, metrics, transcript and research go/no-go | PASS | `MVP_REPORT.md` contains architecture, exact commands/results, Package B trace, action/response boundary and prioritized gate research recommendation. |

## Decision

**GO for the simulated MVP and further research.** Core action-control acceptance
tests and both live integration tests passed in this audit. Close the README and
runbook documentation gaps and complete or continue explicitly qualifying the
real-Hermes bypass evidence before describing all stage items as fully complete.

**NO-GO for real telecom customer transactions.** Trusted identity, customer-channel
restrictions/correlation and an outbound reply approval gate remain necessary
follow-up work. Their deliberate absence is already documented by the MVP plan.
