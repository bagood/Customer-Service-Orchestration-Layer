# Stage 06 verification — private Docker and real Hermes MCP

Verified November 8, 2026. Stage 06 only; Stage 07 evaluation was not started.
All transactions are synthetic local simulations. Hermes source was not changed,
no second Hermes deployment was created, and CSOL never called a Hermes chat API.

## Deployment and compatibility actually tested

| Component | Observed version / path |
| --- | --- |
| Docker Engine / Compose | 28.4.0 / 2.39.4-desktop.1, Docker Desktop on Apple Silicon |
| CSOL interpreter | CPython 3.12.13, `python:3.12.13-slim` pinned to digest `229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36` |
| CSOL dependencies | Existing direct pins unchanged, including MCP SDK **1.30.0**, Pydantic 2.14.3, Starlette 1.10.0, HTTPX 0.28.1 |
| Existing Hermes | **v0.23.0 (2026.9.24), upstream 2bd378ed**, Python 3.14.9, MCP SDK **2.3.0**, OpenAI SDK 2.54.0 |
| Hermes image | `nousresearch/hermes-agent@sha256:adb7890916de63245523492be8f68f9d2095fecbec4e2a6dab7960381f0fc002` (the installed `latest`/`stable` image; overlay pins its digest) |
| Existing Hermes base Compose | `/Users/ariabagusmustikoatmodjo/Downloads/CodingDuniawi/Python-Stuffs/hermes-deployment/docker-compose.yml` |
| Existing Hermes service/container | `hermes` / `hermes-agent`, retained as one deployment |
| CSOL container / endpoint | `csol-csol-1` / **`http://csol:8000/mcp`** on internal `csol-private` bridge |
| Hermes persisted config | Existing `hermes-deployment/data/config.yaml`, mounted at **`/opt/data/config.yaml`**; secret in `/opt/data/.env` |
| CSOL persistent SQLite | `customer-service-orchestration-layer/data/csol.sqlite3`, mounted at `/app/data/csol.sqlite3` |

The SDK version difference required no dependency downgrade or transport change.
The real installed Hermes MCP bridge initialized, discovered, registered and
called the pinned CSOL server successfully. Current upstream documentation was
consulted for context ([MCP reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference),
[MCP guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp));
the installed source and live tests determined the configuration and exact names.

Server-native discovery returned exactly **`csol_process_turn`**, with no cursor.
Hermes registered **`mcp__csol__csol_process_turn`**, toolset `mcp-csol`, alias
`csol`. Whitelisting uses the native name. Both resource and prompt utilities
are disabled; `supports_parallel_tool_calls` is false, connect timeout 10s and
tool timeout 30s. Private transaction functions were never exported.

The installed `_load_mcp_config` resolved `Bearer ${CSOL_BEARER_TOKEN}` from the
persisted profile `.env`; the live probe compared it to the secret without
printing it, then made an authenticated call. A deliberately missing environment
reference was rejected by `_require_rendered_remote`. Real filtered model tool
definitions contained only `mcp__csol__csol_process_turn` after disabling Hermes's
deferred `tool_search` wrappers in the CLI test profile.

## Acceptance gate and evidence

| Required result | Passing evidence |
| --- | --- |
| CSOL-only Compose build/start, one Python server | `docker compose up -d --build`; live Docker test verifies UID/GID 10001 and exactly one `python -m csol.server` process, in addition to Docker's init process |
| Private bridge/DNS, no host publication | Live Docker test inspects `csol-private.Internal=true`, only that network on CSOL, DNS alias `csol`, empty host port bindings and no published network port; `docker compose ps` has an empty PORTS column |
| SQLite bind persistence | Live Docker test checks the bind source/destination, saves Package B in `CONFIRM_PURCHASE` revision 3, restarts CSOL, and requires identical session/cache/ledger state before finishing |
| Authenticated client inside private network | Live Docker test uses `docker compose run --rm --no-deps csol python scripts/mcp_smoke.py --url http://csol:8000/mcp`, including start/finish scenarios, rather than a host-port client |
| Existing Hermes reaches CSOL while retaining egress | Hermes has both `agent-network` and `csol-private`; live Hermes bridge probe and real CLI journey call the private URL |
| Real Hermes discovery and demo turn | `scripts/hermes_mcp_probe.py`, executed in the existing container/venv as `hermes`, passes interpolation, exact discovery/filtered tool definitions and `registry.dispatch` through MCP |
| Real model-driven Package B path | `test_existing_hermes_discovery_and_package_b_customer_to_ledger` passes all five actual CLI/gateway/provider turns, exact arguments/replies and SQLite checks |
| No model omission invented as success | The live test fails on zero/extra calls, wrong arguments, runtime errors or rewritten canonical text; its synthetic trace is retained on failure. No omission occurred on the passing five-turn journey |
| Original credentials/settings retained | Merge-helper tests preserve model/channel/other MCP/env values and private backups; a live comparison with Hermes's own `ruamel.yaml` reader against the original backup found **zero unrelated setting differences** |

The Docker restart test's first completed trace was
`demo-docker-18db84cffcf8434293ddba14a27beb23`, ledger transaction **1**.
Final verification used `demo-docker-ce637f2ac58c4528815c4ead6bbb7e59`,
transaction **3**, and passed in 14.43s with the final image and process checks.
No request supplied authoritative state or a transaction result.

## Customer-to-ledger trace through the real model

Synthetic CSOL session: `demo-hermes-f15660fe5b004d03b1e916dcb052c54e`.
Hermes gateway conversation:
`local-d83cf469b16565a062c81c63bc5798370ba36e3c61f3fa5b513f5befc94c3e14`.
The existing configured provider/model was used without an override.

Each CLI query carried synthetic transport metadata separately from the exact
customer message. Later calls resumed that Hermes conversation. Each turn
emitted exactly one `tool_use` for `mcp__csol__csol_process_turn`, forwarding
the exact message with the listed ID; each final `result.text` equaled the
SQLite-cached canonical `customer_reply` character for character.

| Customer message | Message ID | Saved state / revision | Transaction |
| --- | --- | --- | --- |
| `buy package` | `hermes-b-01` | `SELECT_PACKAGE` / 1 | none |
| `B` | `hermes-b-02` | `ENTER_BALANCE` / 2 | none |
| `20000` | `hermes-b-03` | `CONFIRM_PURCHASE` / 3 | none |
| `yes` | `hermes-b-04` | `FEEDBACK` / 5 | **2 / SUCCEEDED** |
| `skip` | `hermes-b-05` | `IDLE` / 6 | transaction 2 retained, no new transaction |

The ledger row is `(2,
'buy_package:demo-hermes-f15660fe5b004d03b1e916dcb052c54e:1:3',
'SUCCEEDED')`. Five processed-message rows and five audit transitions match
the journey: `workflow_started`, `package_selected`, `balance_accepted`,
`purchase_succeeded`, `feedback_skipped`. Feedback is `(rating=NULL, skipped=1)`.
The internal execution transition accounts for the revision jump from 3 to 5.

The gateway-owned `/opt/data/logs/agent.log` records completed
`mcp__csol__csol_process_turn` calls for that **same Hermes conversation** at
13:14:26, 13:14:31, 13:14:37, 13:14:45 and 13:14:50 UTC (lines 829, 840, 851,
862 and 874 in the observed file). Corresponding CSOL rows were independently
queried. Full synthetic test evidence remains in ignored
`data/stage06-demo-hermes-f15660fe5b004d03b1e916dcb052c54e.json`.

## Observed incompatibilities and smallest corrections

- Docker was initially stopped; `docker version` failed to connect. The ordinary
  sandbox could not start/access Docker. Elevated `docker desktop start` succeeded;
  subsequent authorized Docker commands ran against the existing daemon.
- `hermes version` is not supported; `hermes --version` supplied the release
  metadata. Hermes uses `ruamel.yaml`, so ad hoc diagnostics using `import yaml`
  failed; diagnostics used its existing config reader instead. No Hermes package
  was installed or changed.
- First Docker assertions expected `NetworkSettings.Ports` to contain a null
  `8000/tcp` entry, but an internal network reports `{}` here. Checks now require
  **no bindings at all**, and independently require the exposed TCP port. Compose's
  initial `expose: "8000"` also produced both `8000` and `8000/tcp` metadata keys;
  explicit `8000/tcp` removed the duplicate. Another fixture expected a null
  transaction ID in saved JSON; the existing store omits null fields. The fixture
  was corrected; runtime FSM/auth checks were unchanged.
- The first Hermes tool-surface probe saw `tool_call`, `tool_describe`,
  `tool_search` instead of the concrete MCP tool. The supported
  `tools.tool_search.enabled: "off"` profile setting made the real schema surface
  explicit. Subsequent discovery and model calls passed.
- Real gateway CLI rejected `--run-budget` with exit 2 and no model tokens.
  The live test uses supported options and an external test timeout. It never
  silently falls back to a different provider or local implementation.
- The real CLI then rejected `/opt/data/gateway.sock` mode 0755 with
  `unsafe_control_permissions`; `chmod 600` failed with `Invalid argument` on
  Docker Desktop's bind-mounted Unix socket. The documented Docker-only long
  mount alias selects Hermes's **existing** private socket fallback. This
  preserved `/opt/data`, its credentials and all socket/peer checks. Observed
  socket mode 0600, private parent mode 0700, pointer mode 0600. Actual runtime
  home/socket paths and overlay commands are in the [runbook](private_docker_hermes.md).
- `docker top ... -eo args` lacks the PID field required by this engine and
  failed; `-eo pid,args` works and is the live test's process-count check.

The original persisted files were backed up privately as
`config.yaml.stage06-0d93f3f407e2431ba252e14e090e5f1c.bak` and
`.env.stage06-0d93f3f407e2431ba252e14e090e5f1c.bak`. A second private pair was
made when applying the direct-tool setting. No secret values are included here.
Hermes was recreated/restarted after changes; a fresh CLI used the reloaded
gateway. Hot reload and `/reload-mcp` were not tested.

## Commands and results

All relative commands below run from `customer-service-orchestration-layer/`.
Operational commands requiring Docker/data access used approved elevated shell
access. See the runbook for full merge and Compose overlay command lines.

| Command | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest -q` (baseline) | **592 passed**, 1 existing warning |
| `.venv/bin/python -m pytest tests/test_deployment.py -q` | **6 passed** after adding ambiguous-token rejection |
| `docker compose up -d --build` | Passed; CSOL started healthy, no host port |
| `CSOL_DOCKER_TEST=1 .venv/bin/python -m pytest tests/test_docker_integration.py -q -s` | **1 passed**; authenticated in-network MCP, Package B, restart, ledger |
| `docker compose -f ../../hermes-deployment/docker-compose.yml -f hermes/compose.network.example.yaml -f hermes/compose.docker-desktop.example.yaml up -d hermes` | Passed; existing container recreated, original egress plus private bridge |
| `docker exec -i --user hermes --workdir /opt/hermes hermes-agent .venv/bin/python - < scripts/hermes_mcp_probe.py` | Passed; installed bridge, interpolation, missing-secret rejection, exact tool discovery/surface and call |
| `CSOL_HERMES_TEST=1 .venv/bin/python -m pytest tests/test_hermes_integration.py -q -s` | **1 passed in 31.58s**; five real CLI/model turns, exact canonical replies, successful ledger transaction 2 |
| `.venv/bin/python -m pytest -q` (final offline suite) | **598 passed, 2 opt-in tests skipped**, 1 existing Starlette/HTTPX deprecation warning |
| `.venv/bin/python -m pip check` and `docker compose exec -T csol python -m pip check` | Passed, no broken requirements; pip warned that its cache directory was unwritable |
| `docker compose config --quiet` | Passed, without printing resolved secrets |
| `git diff --check` | Passed |

The opt-in tests are skipped by default because one restarts a live CSOL
container and the other invokes the user's configured model. Each was separately
run and passed. Early failed checks and corrections are recorded above, not
counted as successful acceptance evidence. The API Engineer skill was used for
contract/verification discipline. `postman status` returned `unknown command
'status'` in installed Postman CLI 1.75.0; no Postman workspace, simulation or
external publication was needed or created.

## Touched files and remaining limits

- `Dockerfile`, `.dockerignore`, `compose.yaml`: pinned Python container, minimal
  build context, nonroot single server, healthcheck, SQLite bind, internal bridge.
- `hermes/mcp-config.example.yaml`: private URL, securely interpolated service
  token, native tool whitelist, disabled utilities, sequential calls and timeouts.
- `hermes/customer-service-profile.example.yaml`: restricted CLI toolset, direct
  MCP schema and canonical-reply instructions, explicitly not enforcement.
- `hermes/compose.network.example.yaml`: existing gateway network attachment and
  installed image digest pin; retains original egress.
- `hermes/compose.docker-desktop.example.yaml`: optional tested socket correction.
- `scripts/merge_hermes_config.py`: reviewed-fragment merge, dotenv token update,
  input validation and private atomic writes/backups.
- `scripts/mcp_smoke.py`: authenticated menu and two-phase Package B restart client.
- `scripts/hermes_mcp_probe.py`: installed-runtime compatibility probe.
- `tests/test_deployment.py`, `tests/test_docker_integration.py`,
  `tests/test_hermes_integration.py`: merge safety and opt-in live evidence.
- `.env.example`, `README.md`, `docs/private_docker_hermes.md`, this report; one
  stale deployment comment updated in `src/csol/server.py`.

Runtime artifacts outside Git: ignored CSOL `.env`/SQLite/trace; deliberate
merges/backups in the existing Hermes data directory; existing Docker services
and the new internal network. CSOL and the original Hermes gateway remain
running. The existing Hermes base Compose file and source tree were not edited.

The profile restricts the **CLI test surface**; existing customer-channel toolset
settings were preserved. Applying the same restriction to a real customer
channel and proving that channel's behavior is an additional deployment action.
One model journey does not enforce future tool use or canonical display. Shared
service authentication still does not bind synthetic sessions to customers.
No customer PII, live balance, credit movement, real telecom APIs, gateway reply
gate, multi-worker scaling or production authorization was introduced. Unknown
outcomes remain unconfirmed and cannot trigger blind retries. Stage 06 stops
here for review.
