"""Both workflows share optional feedback and atomic reset to the main menu."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from csol import controller as controller_module
from csol.controller import MENU_REPLY
from csol.models import TurnInput


def send(controller, message):
    return controller.process_turn(TurnInput(
        session_ref="demo-feedback", message_id=uuid4().hex, message=message,
    ))


@pytest.fixture(params=["buy_package", "send_credit"])
def completed(controller, monkeypatch, request):
    purchase = Mock(wraps=controller_module._mock_buy_package)
    transfer = Mock(wraps=controller_module._mock_send_credit)
    monkeypatch.setattr(controller_module, "_mock_buy_package", purchase)
    monkeypatch.setattr(controller_module, "_mock_send_credit", transfer)
    messages = (["buy package", "B", "20000", "yes"] if request.param == "buy_package"
                else ["send credit", "081234567890", "20000", "20000", "yes"])
    for message in messages:
        response = send(controller, message)
    return controller, response, purchase, transfer


def rows(controller, table):
    with controller.store.transaction() as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


@pytest.mark.parametrize("message,rating", [
    ("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5),
    ("skip", None), ("lewati", None), (" SKIP \n", None),
    ("cancel", None), ("batal", None),
])
def test_feedback_persists_and_resets_both_workflows_preserving_history(completed, message, rating):
    controller, before, purchase, transfer = completed
    transactions = rows(controller, "transactions")
    audit = rows(controller, "audit_events")
    response = send(controller, message)
    assert (response.state, response.state_version, response.mode) == (
        "IDLE", before.state_version + 1, "demo",
    )
    assert response.transaction is None
    assert response.allowed_actions == ["buy_package", "send_credit"]
    assert MENU_REPLY in response.customer_reply
    assert rows(controller, "feedback") == [{
        "id": 1, "session_id": "demo-feedback", "rating": rating, "skipped": int(rating is None),
    }]
    with controller.store.transaction() as connection:
        session = dict(connection.execute("SELECT * FROM sessions").fetchone())
    assert session["active_workflow"] is None
    assert session["version"] is None
    assert session["data_json"] == "{}"
    assert rows(controller, "transactions") == transactions
    after_audit = rows(controller, "audit_events")
    assert after_audit[:-1] == audit
    assert after_audit[-1]["event_type"] == (
        "feedback_skipped" if rating is None else "feedback_recorded"
    )
    assert (after_audit[-1]["from_state"], after_audit[-1]["to_state"]) == ("FEEDBACK", "IDLE")
    # An ordinary rating at IDLE cannot create a second feedback row.
    assert send(controller, "5").state == "IDLE"
    assert len(rows(controller, "feedback")) == 1
    next_intent = "send credit" if before.mode == "buy_package" else "buy package"
    routed = send(controller, next_intent)
    assert routed.state == ("ENTER_MSISDN" if before.mode == "buy_package" else "SELECT_PACKAGE")
    assert routed.state_version == response.state_version + 1
    assert rows(controller, "transactions") == transactions
    assert purchase.call_count + transfer.call_count == 1


@pytest.mark.parametrize("message", [
    "0", "6", "-1", "1.0", "01", "５", " 5", "5 ", "5\n", "5 stars", "skip please",
    "lewati now", "yes", "buy package", "send credit", "EXECUTE_TRANSFER",
])
def test_invalid_feedback_holds_state_and_cannot_execute_again(completed, message):
    controller, before, purchase, transfer = completed
    response = send(controller, message)
    assert (response.state, response.state_version) == (before.state, before.state_version)
    assert response.transaction == before.transaction
    assert rows(controller, "feedback") == []
    assert len(rows(controller, "transactions")) == 1
    assert purchase.call_count + transfer.call_count == 1


@pytest.mark.parametrize("corruption", ["status", "transaction_id"])
def test_feedback_checks_its_saved_succeeded_receipt_before_reset(completed, corruption):
    controller, before, purchase, transfer = completed
    with controller.store.transaction() as connection:
        if corruption == "status":
            connection.execute("UPDATE transactions SET status = 'UNKNOWN'")
        else:
            data = json.loads(connection.execute("SELECT data_json FROM sessions").fetchone()[0])
            data["transaction_id"] = before.transaction.transaction_id + 1
            connection.execute("UPDATE sessions SET data_json = ?", (json.dumps(data),))
    with pytest.raises(ValueError):
        send(controller, "5")
    assert rows(controller, "feedback") == []
    with controller.store.transaction() as connection:
        assert connection.execute("SELECT state FROM sessions").fetchone()[0] == "FEEDBACK"
    assert purchase.call_count + transfer.call_count == 1


def test_feedback_reset_and_audit_roll_back_together(completed, monkeypatch):
    controller, before, _, _ = completed
    audit = rows(controller, "audit_events")

    def fail(*args):
        raise RuntimeError("audit failure")

    monkeypatch.setattr(controller.store, "record_event", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        send(controller, "skip")
    assert rows(controller, "feedback") == []
    assert rows(controller, "audit_events") == audit
    assert len(rows(controller, "transactions")) == 1
    with controller.store.transaction() as connection:
        session = connection.execute("SELECT * FROM sessions").fetchone()
    assert (session["state"], session["state_version"]) == ("FEEDBACK", before.state_version)


def test_feedback_reset_then_same_workflow_creates_a_new_transaction(completed):
    controller, before, purchase, transfer = completed
    send(controller, "5")
    messages = (["buy package", "B", "20000", "yes"] if before.mode == "buy_package"
                else ["send credit", "081234567890", "20000", "20000", "yes"])
    for message in messages:
        response = send(controller, message)
    assert response.transaction.transaction_id != before.transaction.transaction_id
    assert len(rows(controller, "transactions")) == 2
    assert len(rows(controller, "feedback")) == 1
    assert purchase.call_count + transfer.call_count == 2
