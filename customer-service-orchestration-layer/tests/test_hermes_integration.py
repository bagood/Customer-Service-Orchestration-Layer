"""Opt-in real Hermes gateway/CLI/model test. Uses the existing provider; incurs inference.

No mocked model, provider override, Hermes source patch or CSOL-to-Hermes API call.
An omitted tool call or rewritten canonical reply fails and leaves a trace.
"""

import json
import math
import os
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERMES = os.environ.get("CSOL_HERMES_CONTAINER", "hermes-agent")
pytestmark = pytest.mark.skipif(
    os.environ.get("CSOL_HERMES_TEST") != "1",
    reason="Set CSOL_HERMES_TEST=1 to use the configured live Hermes model",
)


def test_existing_hermes_discovery_and_package_b_customer_to_ledger():
    probe = subprocess.run(
        ["docker", "exec", "-i", "--user", "hermes", "--workdir", "/opt/hermes", HERMES,
         ".venv/bin/python", "-"],
        input=(ROOT / "scripts/hermes_mcp_probe.py").read_text(),
        text=True, capture_output=True, timeout=90,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert "Hermes MCP probe: PASS" in probe.stdout
    print(probe.stdout, flush=True)
    session_ref = "demo-hermes-" + uuid.uuid4().hex
    trace_path = Path(os.environ.get("CSOL_HERMES_TRACE_PATH", ROOT / "data" / f"stage07-{session_ref}.json"))
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_ref": session_ref, "turns": [], "passed": False,
        "scope": "real configured Hermes CLI/gateway/model; synthetic transport metadata",
        "correlation": "CLI conversation + tool arguments + SQLite processed-message response",
        "customer_channel_coverage": "not measurable: trusted external channel message IDs unavailable",
        "baseline": "baseline not measured",
        "mcp_discovery_probe": probe.stdout.strip().splitlines(),
    }
    hermes_session = None
    transaction_id = None
    journey = [
        ("buy package", "SELECT_PACKAGE", 1),
        ("B", "ENTER_BALANCE", 2),
        ("15000", "ENTER_BALANCE", 2),
        ("25000", "CONFIRM_PURCHASE", 3),
        ("yes", "FEEDBACK", 5),
        ("skip", "IDLE", 6),
    ]
    for index, (message, state, version) in enumerate(journey, 1):
        message_id = f"hermes-b-{index:02}"
        query = (
            f"Synthetic customer-service test transport metadata: session_ref={session_ref}, "
            f"message_id={message_id}. The exact customer message for this turn is: {message}"
        )
        command = [
            "docker", "exec", "-i", HERMES, "hermes", "chat", "-t", "csol",
            "--query-file", "-", "--oneshot", "--format", "stream-json", "--max-turns", "5",
        ]
        if hermes_session:
            command += ["--resume", hermes_session]
        started = time.perf_counter()
        try:
            run = subprocess.run(command, input=query, text=True, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            trace["turns"].append({"message_id": message_id, "error_code": "CLI_TIMEOUT"})
            trace_path.write_text(json.dumps(trace, indent=2) + "\n")
            raise
        events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        terminal = [e for e in events if e.get("type") == "result"]
        calls = [e for e in events if e.get("type") == "tool_use"]
        entry = {
            "message": message, "message_id": message_id, "calls": calls, "result": terminal,
            "end_to_end_latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "expected_state": state, "expected_state_version": version,
            "mcp_call_count": len(calls), "call_correlated": False, "reply_matches": False,
        }
        trace["turns"].append(entry)
        trace_path.write_text(json.dumps(trace, indent=2) + "\n")
        assert run.returncode == 0 and terminal and terminal[-1]["exit_code"] == 0, terminal or run.stderr
        assert len(calls) == 1, f"Observable model bypass/extra call; see {trace_path}"
        assert calls[0]["name"] == "mcp__csol__csol_process_turn"
        assert calls[0]["input"] == {
            "session_ref": session_ref, "message_id": message_id, "message": message,
        }
        hermes_session = terminal[-1]["session_id"]
        assert hermes_session
        with sqlite3.connect(f"file:{ROOT / 'data/csol.sqlite3'}?mode=ro", uri=True) as db:
            cached = db.execute(
                "SELECT response_json FROM processed_messages WHERE session_id=? AND message_id=?",
                (session_ref, message_id),
            ).fetchone()
            assert cached, "Hermes call did not reach the CSOL database"
            entry["call_correlated"] = True
            payload = json.loads(cached[0])
            saved = db.execute("SELECT state,state_version FROM sessions WHERE session_id=?", (session_ref,)).fetchone()
            assert saved == (state, version)
            assert (payload["state"], payload["state_version"]) == (state, version)
            assert terminal[-1]["text"] == payload["customer_reply"], f"Canonical reply mismatch; see {trace_path}"
            entry["reply_matches"] = True
            transactions = db.execute(
                "SELECT id,status FROM transactions WHERE idempotency_key=?", (f"buy_package:{session_ref}:1:3",),
            ).fetchall()
            if index < 5:
                assert transactions == []
                assert payload["transaction"] is None
            else:
                assert len(transactions) == 1 and transactions[0][1] == "SUCCEEDED"
                transaction_id = transactions[0][0]
            if index == 5:
                assert payload["transaction"] == {"transaction_id": transaction_id, "status": "SUCCEEDED"}
                assert "Demo purchase SUCCEEDED" in payload["customer_reply"]
        entry["canonical_response"] = payload
        trace_path.write_text(json.dumps(trace, indent=2) + "\n")
        print(f"Hermes customer {message!r} -> {state} revision {version}; canonical reply matches", flush=True)

    # Inspect the gateway-owned runtime log, printing only the matching fixed tool name.
    check_log = (
        "from pathlib import Path; "
        "log=Path('/opt/data/logs/agent.log').read_text(); "
        "assert 'mcp__csol__csol_process_turn' in log; "
        "print('Gateway agent.log contains mcp__csol__csol_process_turn: PASS')"
    )
    log = subprocess.run(
        ["docker", "exec", HERMES, "/opt/hermes/.venv/bin/python", "-c", check_log],
        text=True, capture_output=True, timeout=10,
    )
    assert log.returncode == 0, log.stderr
    print(log.stdout, flush=True)
    trace["hermes_session"] = hermes_session
    trace["transaction_id"] = transaction_id
    trace["passed"] = True
    # CLI token counters may be cumulative across --resume turns. Preserve the
    # raw per-result counters; do not sum them or invent model-token savings.
    latencies = sorted(t["end_to_end_latency_ms"] for t in trace["turns"])
    trace["summary"] = {
        "turns": len(trace["turns"]),
        "correlated_mcp_turns": sum(t["call_correlated"] for t in trace["turns"]),
        "exact_reply_turns": sum(t["reply_matches"] for t in trace["turns"]),
        "mcp_call_count": sum(t["mcp_call_count"] for t in trace["turns"]),
        "latency_scope": "per CLI subprocess including gateway/provider/tool/final reply and Docker overhead",
        "latency_method": "nearest rank, six synthetic turns; not a benchmark",
        **{f"p{p}_end_to_end_ms": latencies[math.ceil(len(latencies) * p / 100) - 1] for p in (50, 95)},
        "tokens": "raw Hermes CLI result counters retained per turn; aggregation semantics unverified",
    }
    trace_path.write_text(json.dumps(trace, indent=2) + "\n")
    print(f"Hermes customer-to-ledger trace: {trace_path}; transaction={transaction_id}", flush=True)
