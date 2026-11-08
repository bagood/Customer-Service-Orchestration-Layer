"""Opt-in live test: build/start Compose first; this test restarts CSOL only."""

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("CSOL_DOCKER_TEST") != "1", reason="Set CSOL_DOCKER_TEST=1 for live private Docker checks",
)


def run(*args):
    completed = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def compose(*args):
    return run("docker", "compose", *args)


def wait_healthy(cid):
    for _ in range(45):
        if run("docker", "inspect", cid, "--format", "{{.State.Health.Status}}") == "healthy":
            return
        time.sleep(1)
    pytest.fail("CSOL did not become healthy")


def ledger(session_ref):
    code = f'''
import json, sqlite3
c = sqlite3.connect('/app/data/csol.sqlite3')
c.row_factory = sqlite3.Row
s = {session_ref!r}
sql = "SELECT * FROM transactions WHERE idempotency_key=?"
print(json.dumps({{
    'session': dict(c.execute('SELECT * FROM sessions WHERE session_id=?', (s,)).fetchone()),
    'transactions': [dict(r) for r in c.execute(sql, (f'buy_package:{{s}}:1:3',))],
    'processed': c.execute('SELECT count(*) FROM processed_messages WHERE session_id=?', (s,)).fetchone()[0],
}}))
'''
    return json.loads(compose("exec", "-T", "csol", "python", "-c", code))


def test_private_mcp_package_b_survives_container_restart():
    cid = compose("ps", "-q", "csol")
    assert cid, "Start CSOL with docker compose up -d --build first"
    wait_healthy(cid)
    assert run("docker", "inspect", cid, "--format", "{{.Config.User}}") == "10001:10001"
    processes = run("docker", "top", cid, "-eo", "pid,args")
    assert len(re.findall(r"^\d+\s+python -m csol\.server\s*$", processes, re.M)) == 1
    # Inspect only non-secret fields, never .Config.Env or resolved compose config.
    assert json.loads(run("docker", "inspect", cid, "--format", "{{json .HostConfig.PortBindings}}")) in ({}, None)
    ports = json.loads(run("docker", "inspect", cid, "--format", "{{json .NetworkSettings.Ports}}"))
    assert all(binding is None for binding in ports.values())
    exposed = json.loads(run("docker", "inspect", cid, "--format", "{{json .Config.ExposedPorts}}"))
    assert exposed == {"8000/tcp": {}}
    networks = json.loads(run("docker", "inspect", cid, "--format", "{{json .NetworkSettings.Networks}}"))
    assert list(networks) == ["csol-private"]
    assert "csol" in networks["csol-private"]["Aliases"]
    assert run("docker", "network", "inspect", "csol-private", "--format", "{{.Internal}}") == "true"
    mounts = json.loads(run("docker", "inspect", cid, "--format", "{{json .Mounts}}"))
    assert any(m["Type"] == "bind" and m["Source"] == str(ROOT / "data") and m["Destination"] == "/app/data" for m in mounts)

    session_ref = "demo-docker-" + uuid.uuid4().hex

    def smoke(scenario):
        output = compose(
            "run", "--rm", "--no-deps", "csol", "python", "scripts/mcp_smoke.py",
            "--url", "http://csol:8000/mcp", "--scenario", scenario, "--session-ref", session_ref,
        )
        assert "tools/list: OK (csol_process_turn)" in output
        assert "MCP smoke: PASS" in output

    smoke("menu")
    # Menu and purchase use distinct message IDs in the same synthetic session.
    smoke("package-b-start")
    before = ledger(session_ref)
    assert (before["session"]["state"], before["session"]["state_version"]) == ("CONFIRM_PURCHASE", 3)
    assert json.loads(before["session"]["data_json"]) == {"package": "B", "balance_idr": 20000}
    assert before["transactions"] == []
    compose("restart", "csol")
    wait_healthy(cid)
    assert ledger(session_ref) == before
    smoke("package-b-finish")
    after = ledger(session_ref)
    assert (after["session"]["state"], after["session"]["state_version"]) == ("IDLE", 6)
    assert len(after["transactions"]) == 1
    assert after["transactions"][0]["status"] == "SUCCEEDED"
    assert after["processed"] == 6  # menu + 5 purchase turns; replay added no row
    print(f"Private Docker/restart trace: {session_ref}; transaction={after['transactions'][0]['id']}")
