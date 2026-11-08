"""Private, deterministic in-process mocks. Never register these as MCP tools."""

from csol.models import PurchaseTransaction


def _mock_buy_package(transaction_id: int) -> PurchaseTransaction:
    """Simulate a purchase receipt; no network, balance lookup or credit movement."""
    return PurchaseTransaction(transaction_id=transaction_id, status="SUCCEEDED")


def _mock_send_credit(transaction_id: int) -> PurchaseTransaction:
    """Simulate a transfer receipt; no network, balance lookup or credit movement."""
    return PurchaseTransaction(transaction_id=transaction_id, status="SUCCEEDED")
