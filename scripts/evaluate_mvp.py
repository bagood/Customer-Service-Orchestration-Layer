"""Offline Stage 07 evidence; real MCP/ASGI, temporary SQLite, synthetic inputs only.

Run from the repository: .venv/bin/python scripts/evaluate_mvp.py
Parallel confirmation uses two controller threads (not ASGI latency). Client reply
bypasses are controlled fixtures, NOT claims about observed Hermes behavior.
"""

import argparse
import asyncio
import contextvars
import json
import logging
import math
import os
import platform
import re
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from csol import controller as controller_module
from csol.config import load_configuration, normalize
from csol.controller import Controller
from csol.models import TurnInput, TurnResponse
from csol.server import create_app
from csol.store import Store

ROOT = Path(__file__).resolve().parents[1]
CURRENT_TURN = contextvars.ContextVar("evaluation_turn", default=None)


def percentiles(values):
    """Nearest-rank percentiles; no inference beyond the measured sample."""
    ordered = sorted(values)
    return {f"p{p}_ms": round(ordered[math.ceil(len(ordered) * p / 100) - 1], 3)
            if ordered else None for p in (50, 95)}


def snapshot(path):
    with sqlite3.connect(path) as db:
        state = db.execute("SELECT state FROM sessions").fetchone()
        return {
            "state": state[0] if state else "IDLE",
            "transactions": [r[0] for r in db.execute("SELECT status FROM transactions ORDER BY id")],
            "feedback": [list(r) for r in db.execute("SELECT rating,skipped FROM feedback ORDER BY id")],
            "reason": (db.execute("SELECT event_type FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
                       or [None])[0],
        }


def tracked_turn(original):
    def invoke(self, turn):
        token = CURRENT_TURN.set(turn)
        try:
            return original(self, turn)
        finally:
            CURRENT_TURN.reset(token)
    return invoke


def instrument(operation, workflow, path, invocations):
    def invoke(transaction_id, **kwargs):
        turn = CURRENT_TURN.get()
        # Independently observe exact confirmation, persisted prerequisites and
        # durable reservation at the invocation boundary. Never export data_json.
        with sqlite3.connect(path) as db:
            row = db.execute("SELECT state,data_json FROM sessions WHERE session_id=?",
                             (turn.session_ref if turn else "",)).fetchone()
            record = db.execute("SELECT idempotency_key,status FROM transactions WHERE id=?",
                                (transaction_id,)).fetchone()
        data = json.loads(row[1]) if row else {}
        if workflow == "buy_package":
            price = {"A": 10000, "B": 20000}.get(data.get("package"))
            prerequisites = price is not None and data.get("balance_idr", -1) >= price
            state = "CONFIRM_PURCHASE"
        else:
            amount = data.get("amount_idr", 0)
            prerequisites = (re.fullmatch(r"628[0-9]{8,11}", data.get("msisdn", "")) is not None
                             and amount > 0 and data.get("balance_idr", -1) >= amount)
            state = "CONFIRM_TRANSFER"
        authorized = bool(turn and normalize(turn.message) in {"yes", "ya"}
                          and row and row[0] == state and prerequisites and record
                          and record[0].startswith(f"{workflow}:{turn.session_ref}:")
                          and record[1] == "PENDING")
        invocations.append({"workflow": workflow, "transaction_id": transaction_id,
                            "authorized": authorized})
        return operation(transaction_id, **kwargs)
    return invoke


@asynccontextmanager
async def connect(app, discoveries):
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers={
                "Authorization": "Bearer " + os.environ["CSOL_BEARER_TOKEN"],
            }) as http,
            streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = [tool.name for tool in listed.tools]
            if initialized.serverInfo.name != "csol" or names != ["csol_process_turn"] or listed.nextCursor:
                raise AssertionError("Unexpected MCP discovery")
            discoveries.append({"server": initialized.serverInfo.model_dump(mode="json"),
                                "protocol": initialized.protocolVersion, "tools": names})
            yield session


async def evaluate_case(case, path):
    invocations, discoveries, turns, failures, latencies = [], [], [], [], []
    mcp_calls = 0
    response = None
    session_ref = "demo-eval-" + case["id"]
    with (
        patch.dict(os.environ, {"CSOL_BEARER_TOKEN": "stage07-ephemeral-" + "x" * 32}),
        patch.object(Controller, "process_turn", tracked_turn(Controller.process_turn)),
        patch.object(controller_module, "_mock_buy_package", instrument(
            controller_module._mock_buy_package, "buy_package", path, invocations)),
        patch.object(controller_module, "_mock_send_credit", instrument(
            controller_module._mock_send_credit, "send_credit", path, invocations)),
    ):
        async with AsyncExitStack() as stack:
            app = create_app(db_path=path)
            app.state.controller._test_mock_outcome = case.get("mock_outcome", "SUCCEEDED")
            session = await stack.enter_async_context(connect(app, discoveries))
            for index, step in enumerate(case["steps"]):
                action = step.get("action", "turn")
                before = snapshot(path)
                started = time.perf_counter()
                count = 0
                visible = None
                try:
                    if action == "restart":
                        await stack.aclose()
                        app = create_app(db_path=path)
                        app.state.controller._test_mock_outcome = case.get("mock_outcome", "SUCCEEDED")
                        session = await stack.enter_async_context(connect(app, discoveries))
                    elif action == "parallel_confirm":
                        # Existing test_hardening.py additionally forces the lock
                        # and reservation-gap interleavings for both workflows.
                        barrier = Barrier(2)
                        def confirm(number):
                            controller = Controller(Store(path), load_configuration())
                            barrier.wait(timeout=3)
                            return controller.process_turn(TurnInput(
                                session_ref=session_ref, message_id=f"parallel-{number}", message="yes"))
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            futures = [pool.submit(confirm, n) for n in range(2)]
                            replies = [f.result(timeout=5) for f in futures]
                        response = replies[0]
                        if any(r.transaction and r.transaction.status != "SUCCEEDED" for r in replies):
                            raise AssertionError("Invalid parallel receipt")
                    elif action == "client_reply":
                        visible = step["visible_reply"]
                        # A deliberately noncompliant Hermes-output fixture is
                        # outside the MCP server. No channel gate exists here.
                    else:
                        arguments = {"session_ref": session_ref,
                                     "message_id": step.get("message_id", f"turn-{index}"),
                                     "message": step["message"]} | step.get("extra_arguments", {})
                        count = 1
                        result = await session.call_tool("csol_process_turn", arguments)
                        response = TurnResponse.model_validate(result.structuredContent)
                        if json.loads(result.content[0].text) != result.structuredContent:
                            raise AssertionError("Text/structured MCP response mismatch")
                        if result.isError != (response.error_code is not None):
                            raise AssertionError("MCP error flag mismatch")
                    elapsed = (time.perf_counter() - started) * 1000
                    if count:
                        latencies.append(elapsed)
                    actual = snapshot(path) | {"mock_calls": len(invocations)}
                    actual["error_code"] = response.error_code if response else None
                    expected = {"transactions": [], "mock_calls": 0} | step["expect"]
                    if response:
                        actual["response_state"] = response.state
                        actual["response_transaction"] = (
                            response.transaction.model_dump() if response.transaction else None)
                    if action == "turn":
                        expected["response_state"] = (
                            "UNAVAILABLE" if expected.get("error_code") else expected["state"])
                        expected["response_transaction"] = (
                            {"transaction_id": 1, "status": "SUCCEEDED"}
                            if expected["state"] == "FEEDBACK" else None)
                    if action == "client_reply":
                        actual["ledger_unchanged"] = before == snapshot(path)
                        actual["reply_fidelity"] = bool(response and visible == response.customer_reply)
                    for key, value in expected.items():
                        if actual.get(key) != value:
                            failures.append(f"step {index}: {key}: expected {value!r}, got {actual.get(key)!r}")
                    if action == "turn" and response:
                        if actual["error_code"] is None and response.state != actual["state"]:
                            # Replayed responses intentionally describe the earlier turn.
                            if not step.get("replay"):
                                failures.append(f"step {index}: response/saved state mismatch")
                        if response.transaction and "SUCCEEDED" not in actual["transactions"]:
                            failures.append(f"step {index}: receipt without ledger success")
                        if "SUCCEEDED" in response.customer_reply and response.transaction is None:
                            failures.append(f"step {index}: success wording without receipt")
                    # Input text is omitted: recipients and prompt attacks stay
                    # in the synthetic fixture, never in exported turn traces.
                    turns.append({"step": index, "action": action, "expected": expected, "actual": actual,
                                  "mcp_call_count": count, "latency_ms": round(elapsed, 3),
                                  "latency_scope": "MCP/ASGI round trip" if count else "local harness operation",
                                  "customer_reply": response.customer_reply if response else None,
                                  "visible_reply": visible})
                except Exception as error:
                    failures.append(f"step {index}: {type(error).__name__}")
                    break
                finally:
                    mcp_calls += count
    unauthorized = sum(not call["authorized"] for call in invocations)
    duplicate = sum(n - 1 for n in Counter((c["workflow"], c["transaction_id"]) for c in invocations).values())
    if unauthorized or duplicate:
        failures.append("Unauthorized or duplicate private mock invocation")
    return {"id": case["id"], "kind": case.get("kind", "workflow"), "passed": not failures,
            "failures": failures, "turns": turns, "simulated_transaction_count": len(invocations),
            "unauthorized_mock_executions": unauthorized, "duplicate_mock_executions": duplicate,
            "mcp_call_count": mcp_calls, "mcp_discovery": discoveries,
            "mcp_latency": percentiles(latencies), "mcp_latency_samples_ms": [round(v, 3) for v in latencies]}


async def evaluate(cases):
    results = []
    with TemporaryDirectory(prefix="csol-stage07-") as directory:
        for index, case in enumerate(cases):
            results.append(await evaluate_case(case, Path(directory) / f"case-{index}.sqlite3"))
    samples = [v for result in results for v in result["mcp_latency_samples_ms"]]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "mcp": version("mcp")},
        "scope": "synthetic local MCP/ASGI and SQLite; parallel confirms use controller threads",
        "bypass_scope": "controlled noncompliant client fixtures, not observed Hermes model behavior",
        "summary": {"scenarios": len(results), "passed": sum(r["passed"] for r in results),
                    "failed": sum(not r["passed"] for r in results),
                    "simulated_transaction_count": sum(r["simulated_transaction_count"] for r in results),
                    "unauthorized_mock_executions": sum(r["unauthorized_mock_executions"] for r in results),
                    "duplicate_mock_executions": sum(r["duplicate_mock_executions"] for r in results),
                    "mcp_call_count": sum(r["mcp_call_count"] for r in results),
                    "mcp_latency": percentiles(samples)},
        "hermes_chat": "not measured by this offline runner; see separate live CLI trace",
        "customer_channel_coverage": "not measurable: no trusted channel identity/message correlation",
        "baseline": "baseline not measured",
        "production_safety": "BLOCKED: trusted channel identity and outbound approval gate absent",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=ROOT / "evaluation/scenarios.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/results.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    cases = json.loads(args.scenarios.read_text())
    if len(cases) < 15 or len({case["id"] for case in cases}) != len(cases):
        parser.error("At least 15 uniquely named scenarios required")
    report = asyncio.run(evaluate(cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    print(f"Evidence: {args.output}")
    raise SystemExit(1 if report["summary"]["failed"] else 0)


if __name__ == "__main__":
    main()
