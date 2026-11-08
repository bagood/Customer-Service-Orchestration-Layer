"""Private, deterministic in-process mocks. Never register these as MCP tools."""

from csol.models import PurchaseTransaction


def _mock_buy_package(transaction_id: int) -> PurchaseTransaction:
    """Simulate a purchase receipt; no network, balance lookup or credit movement."""
    return PurchaseTransaction(transaction_id=transaction_id, status="SUCCEEDED")
