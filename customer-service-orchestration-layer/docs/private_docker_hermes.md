# Private Docker and existing Hermes runbook

Run from `customer-service-orchestration-layer/`. CSOL remains the MCP server;
Hermes remains the MCP client. This deploys **CSOL only** by default, with one
Python server process. The existing Hermes installation is reused.

## Start CSOL

Install the pinned dependencies into `.venv` as described in the README. Create
the service secret once in an ignored, private `.env`, without printing it:

```sh
.venv/bin/python - <<'PY'
import os, secrets
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('CSOL_BEARER_TOKEN=' + secrets.token_urlsafe(32) + '\n')
PY
docker compose up -d --build
docker compose ps
docker compose run --rm --no-deps csol python scripts/mcp_smoke.py --url http://csol:8000/mcp
CSOL_DOCKER_TEST=1 .venv/bin/python -m pytest tests/test_docker_integration.py -q -s
```

If `.env` already exists, reuse its valid token; the creation command deliberately
refuses to overwrite it. Compose loads it; bare Python does not. Never run
`docker compose config` or inspect container environment values into shared logs:
those can contain the resolved secret.

`csol-private` is a named **internal bridge**. The service/DNS alias is `csol`.
There is no `ports` mapping: `8000/tcp` is exposed only as container metadata.
The MCP URL for authorized attached containers is `http://csol:8000/mcp`.
CSOL has no runtime egress network. Building the image needs registry/package
access. The healthcheck deliberately expects an unauthenticated 401; authenticated
protocol initialization, discovery and calls are tested by the smoke client.

SQLite lives at `/app/data/csol.sqlite3`, bind-mounted from `./data`. The server
runs as UID/GID `10001:10001`; on native Linux, provision that directory writable
by this UID before starting (for example `sudo chown 10001:10001 data`). Docker
Desktop was tested with the existing host-owned directory. Do not scale the
service or add workers. `docker compose down` does not remove bind-mounted data.
Back up SQLite only while CSOL is stopped or with SQLite's backup API.

## Attach the existing Hermes stack

The discovered base project is `../../hermes-deployment/docker-compose.yml`,
service `hermes`, container `hermes-agent`, with its existing `agent-network`
for provider/channel egress. Its `./data` is mounted at `/opt/data`.
`hermes/compose.network.example.yaml` adds the external `csol-private` network
and pins the **already-installed** Hermes image digest. Review service and
network names if applying this on a different installation.

Merge the fragments; do not replace the existing config with either example:

```sh
.venv/bin/python scripts/merge_hermes_config.py \
  --config ../../hermes-deployment/data/config.yaml \
  --env ../../hermes-deployment/data/.env \
  --token-file .env \
  --fragment hermes/mcp-config.example.yaml \
  --fragment hermes/customer-service-profile.example.yaml
docker compose -f ../../hermes-deployment/docker-compose.yml \
  -f hermes/compose.network.example.yaml up -d hermes
```

The helper validates all inputs before writing, preserves unrelated YAML values
and dotenv lines, and creates mode-0600 `.stage06-<id>.bak` backups beside both
files. It writes the token only to Hermes `.env`; config retains the literal
`${CSOL_BEARER_TOKEN}` reference. YAML comments/formatting may change. For rollback,
restore both matching backups while Hermes is stopped and recreate/restart it.
The first backup pair predates all Stage 06 settings. Treat backups as secrets.

The profile fragment sets CLI toolsets to `[csol]`, disables deferred tool search
wrappers, and installs `agent.system_prompt`. It preserves the existing model,
provider, channel credentials and other channel toolsets. For an actual customer
channel, explicitly set **that channel's** `platform_toolsets` to `[csol]` and
verify its offered tools too; this stage tests the CLI customer-service profile.
No telecom credentials belong in Hermes. The canonical-reply prompt is
**instruction, not enforcement**; a live model omission/mismatch fails the test.
Session references are synthetic and do not authenticate customers.

As an alternative to an overlay, `docker network connect csol-private hermes-agent`
attaches a currently running container, retaining its existing network. This
survives container restart but not recreation. Always use the overlay with the
original base file on subsequent Compose recreation; never run it as a separate
Hermes project. Do not publish CSOL just to reach it from the host.

## Installed Hermes Docker Desktop socket correction

On this Docker Desktop installation, the pinned Hermes release creates
`/opt/data/gateway.sock` as `0755`; `chmod 600` fails with `Invalid argument`.
The CLI refuses it with `unsafe_control_permissions` before model inference.
The optional `hermes/compose.docker-desktop.example.yaml` mounts the **same**
persistent data at a second, deliberately long path and sets `HERMES_HOME` to
it. Hermes's existing long-path logic then uses its private temporary Unix socket
and `gateway.sock.path` pointer. The original `/opt/data` mount remains available.
No source or permission-check change, new Hermes deployment or TCP control socket
is involved. Use this overlay only for that observed incompatibility:

```sh
docker compose -f ../../hermes-deployment/docker-compose.yml \
  -f hermes/compose.network.example.yaml \
  -f hermes/compose.docker-desktop.example.yaml up -d hermes
```

Verified runtime home:
`/opt/hermes-runtime/private-control-socket-fallback-for-docker-desktop-bind-mounts/persistent-profile-data`.
It sees the very same persisted `config.yaml`, `.env`, credentials and state as
`/opt/data`. The private socket observed was
`/tmp/hermes-runtime/hermes-gw-cbee7bb370e05d58/control.sock` (mode 0600, private
parent directory). The pointer is mode 0600. Its hash/path may differ elsewhere.
Keep all three Compose files on later recreation in this environment.

## Verify Hermes, with its own configured model

After config or secret changes, recreate/restart the existing container. This
was the tested reload procedure. A fresh CLI session uses the gateway's newly
loaded config; `/reload-mcp` and hot reload were not independently tested.

```sh
docker exec -i --user hermes --workdir /opt/hermes hermes-agent \
  .venv/bin/python - < scripts/hermes_mcp_probe.py
CSOL_HERMES_TEST=1 .venv/bin/python -m pytest tests/test_hermes_integration.py -q -s
```

The first command tests the **installed** Hermes bridge, persisted config,
interpolation (including a missing-secret rejection), discovery, actual filtered
model tool definitions, and a real MCP turn. It does not invoke a model. The
second incurs model inference through the existing CLI/gateway/provider, using
five separate customer messages: `buy package`, `B`, `20000`, `yes`, `skip`.
Each CLI invocation uses `hermes chat -t csol --query-file - --oneshot --format
stream-json --max-turns 5`, with `--resume` after the first. Do not add
`--run-budget`: this pinned gateway rejects that CLI option. Use configured
`agent.run_budget_seconds` if an operator needs a gateway execution budget.

The test requires exactly one actual CSOL tool call per customer turn, correct
arguments, exact final canonical text, matching SQLite cache/state rows, no
transaction before confirmation, and one recorded `SUCCEEDED` receipt afterward.
It checks the gateway-owned `agent.log` for the registered tool name and stores
a synthetic JSON trace under ignored `data/stage06-demo-hermes-*.json`. Failure
leaves evidence rather than asserting success. This is one integration journey,
not the Stage 07 evaluation suite or proof that every future reply is gated.

Server-native discovery: `csol_process_turn`. Hermes v0.23.0 registers
`mcp__csol__csol_process_turn` in toolset `mcp-csol`, with alias `csol`.
Whitelist names in `mcp_servers.csol.tools.include` are **server-native** names.
Do not whitelist the Hermes wrapper name or expose private mock functions.
Resources/prompts are disabled, calls are sequential, connect timeout is 10s and
tool timeout is 30s. Unknown outcomes still require review with no blind retry.
