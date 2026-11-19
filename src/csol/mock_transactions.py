"""Private, deterministic in-process mocks. Never register these as MCP tools."""

from typing import Literal

from csol.models import MockResult

TestOutcome = Literal["SUCCEEDED", "FAILED", "UNKNOWN", "TIMEOUT"]


def _result(transaction_id: int, outcome: TestOutcome) -> MockResult:
    if outcome == "TIMEOUT":
        # Deterministic, immediate timeout: no sleeps or external side effects.
        raise TimeoutError("Synthetic mock timeout")
    return MockResult(transaction_id=transaction_id, status=outcome)


def _mock_buy_package(
    transaction_id: int, *, _test_outcome: TestOutcome = "SUCCEEDED",
) -> MockResult:
    """Simulate a purchase receipt; no network, balance lookup or credit movement."""
    return _result(transaction_id, _test_outcome)


def _mock_send_credit(
    transaction_id: int, *, _test_outcome: TestOutcome = "SUCCEEDED",
) -> MockResult:
    """Simulate a transfer receipt; no network, balance lookup or credit movement."""
    return _result(transaction_id, _test_outcome)
