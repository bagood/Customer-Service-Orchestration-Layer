# Stage 01 verification

Verified November 8, 2026, using CPython 3.12.13 and MCP SDK 1.30.0.
Commands below run from `customer-service-orchestration-layer/`.

## Automated checks

```text
$ .venv/bin/python -m pytest -q
88 passed, 1 warning
```

The warning is Starlette's deprecation notice for its test client's HTTPX
integration. The pinned MCP SDK uses HTTPX; all tests pass. Stage 01 uses the
SDK's current `streamable_http_client` entrypoint, while the existing Stage 00
import test still checks the compatible legacy import.

Passing tests cover official-client initialize/list/call; exactly one public
tool; strict Pydantic input/output validation; missing/invalid/duplicate bearer
headers; every HTTP method's authentication boundary; authentication before
dispatch/body reads; missing server token; fixed menu with no state/files
created; Docker/local Host and Origin acceptance; disallowed Host/Origin
rejection; unknown tools; safe internal-failure responses; output-failure
rejection; body limits with and without Content-Length; malformed JSON;
and absence of custom chat or backend routes. Both Stage 00 tests still pass.

Other passing commands:

```text
$ PIP_CACHE_DIR=/tmp/csol-stage01-pip-cache .venv/bin/python -m pip install --no-deps -e .
Successfully installed customer-service-orchestration-layer-0.0.0
$ .venv/bin/python -m pip check
No broken requirements found.
$ git diff --check
(exit 0, no output)
```

The editable install uses isolated build dependencies and preserves all pinned
runtime dependencies already installed in the project environment.

## Live smoke

The server command was:

```sh
.venv/bin/python -m csol.server
```

The exact official MCP client command was:

```sh
.venv/bin/python scripts/mcp_smoke.py --url http://127.0.0.1:8000/mcp
```

Both processes received the same freshly generated `CSOL_BEARER_TOKEN` through
their environments. The token was not printed or written to a file. The server
was terminated after verification. The smoke command exited zero and printed:

```text
initialize: OK (server=csol)
tools/list: OK (csol_process_turn)
tools/call: OK
{
  "session_ref": "demo-smoke",
  "mode": "demo",
  "state": "MENU",
  "state_version": 0,
  "customer_reply": "Telecom demo menu (simulation only):\n1. Buy a package (buy_package)\n2. Send credit (send_credit)\nWorkflows are not available yet. No transaction has been executed.",
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

Additional HTTP checks against that running process printed:

```text
Live missing token: 401 OK
Live invalid token: 401 OK
Live bad Host: 421 OK
Live bad Origin: 403 OK
Live Docker Host/Origin: 200 OK
```

The Docker check supplies `Host: csol:8000` and `Origin: http://csol:8000` to
the local live endpoint; it verifies header policy, not Docker networking.
No Docker deployment or real Hermes session was exercised in this stage.

## Environment issues observed

The first live-check launcher failed at its local port-bind probe with
`PermissionError: [Errno 1] Operation not permitted` in the execution sandbox.
The identical launcher passed after permission to run the temporary local
listener was granted. No security controls were disabled.

An optional offline reinstall attempt,
`.venv/bin/python -m pip install --no-build-isolation --no-deps -e .`, failed
with `BackendUnavailable: Cannot import 'setuptools.build_meta'`: setuptools is
available through isolated build setup, not installed in the runtime venv.
The normal isolated command shown above first failed in the sandbox because
DNS/network access to fetch setuptools was restricted; rerunning it with
network permission passed. The build pin was not changed.

The API Engineer skill's auxiliary `postman status` command exited 1 with
`error: unknown command 'status'`. No Postman setup, workspace, or contract was
used or changed. MCP validation uses the official SDK and pytest directly.

## Files touched

- `.env.example`: required deployment token documentation.
- `README.md`: Stage 01 setup, commands, contract, security policy, and limits.
- `pyproject.toml`: project description.
- `requirements.txt`: direct pins for imported ASGI/HTTP dependencies.
- `src/csol/__init__.py`: Stage 01 package description.
- `src/csol/auth.py`: fail-closed token loading and authentication middleware.
- `src/csol/models.py`: strict request/response contract.
- `src/csol/server.py`: one tool, fixed menu, safe errors, secured HTTP transport.
- `scripts/mcp_smoke.py`: live official-client connectivity check.
- `tests/test_mcp_server.py`: acceptance and rejection tests.
- `docs/stage_01_verification.md`: this evidence report.

Routing, persistence, workflows, transactions, Docker deployment, and Hermes
configuration are intentionally deferred to their numbered stages.
