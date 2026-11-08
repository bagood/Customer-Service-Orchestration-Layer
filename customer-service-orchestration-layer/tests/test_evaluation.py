"""The reusable evidence must detect regressions and disclose client limitations."""

import asyncio
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from csol import controller as controller_module
from csol.controller import Controller

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evaluate_mvp", ROOT / "scripts/evaluate_mvp.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
CASES = json.loads((ROOT / "evaluation/scenarios.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_synthetic_scenario_evidence(case, tmp_path):
    result = asyncio.run(evaluation.evaluate_case(case, tmp_path / "scenario.sqlite3"))
    assert result["passed"], result["failures"]
    assert result["unauthorized_mock_executions"] == result["duplicate_mock_executions"] == 0
    assert result["mcp_discovery"][0]["tools"] == ["csol_process_turn"]
    # Exported evidence contains approved masked replies, never raw recipients.
    encoded = json.dumps(result)
    for raw in ("081234567890", "6281234567890"):
        assert raw not in encoded
    if case.get("kind") == "controlled_client_bypass":
        bypass = result["turns"][-1]
        assert bypass["mcp_call_count"] == 0
        assert bypass["actual"]["ledger_unchanged"] is True
        assert bypass["actual"]["reply_fidelity"] is False


def test_runner_exits_nonzero_and_retains_failed_expectations(tmp_path):
    cases = copy.deepcopy(CASES)
    cases[0]["steps"][-1]["expect"]["transactions"] = ["FAILED"]
    fixture, output = tmp_path / "scenarios.json", tmp_path / "results.json"
    fixture.write_text(json.dumps(cases))
    run = subprocess.run([
        sys.executable, str(ROOT / "scripts/evaluate_mvp.py"),
        "--scenarios", str(fixture), "--output", str(output),
    ], capture_output=True, text=True, timeout=30)
    assert run.returncode == 1, run.stderr
    report = json.loads(output.read_text())
    assert report["summary"]["failed"] == 1
    assert report["results"][0]["failures"]
    assert report["baseline"] == "baseline not measured"
    assert report["customer_channel_coverage"].startswith("not measurable")


@pytest.mark.parametrize("violation", ["unauthorized", "duplicate"])
def test_instrumentation_detects_bad_mock_invocations(monkeypatch, tmp_path, violation):
    original = Controller.process_turn

    def faulty(self, turn):
        if violation == "unauthorized" and turn.message == "buy package":
            controller_module._mock_buy_package(999)
        response = original(self, turn)
        if violation == "duplicate" and response.transaction:
            controller_module._mock_buy_package(response.transaction.transaction_id)
        return response

    monkeypatch.setattr(Controller, "process_turn", faulty)
    result = asyncio.run(evaluation.evaluate_case(CASES[0], tmp_path / "fault.sqlite3"))
    assert not result["passed"]
    assert result["unauthorized_mock_executions"] == 1
    assert result["duplicate_mock_executions"] == int(violation == "duplicate")
