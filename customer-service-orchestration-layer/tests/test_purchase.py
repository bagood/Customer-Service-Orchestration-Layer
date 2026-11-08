"""Stage 03 acceptance gates and the purchase controller's safety boundaries."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from csol import controller as controller_module
from csol.config import load_configuration
from csol.controller import Controller
from csol.models import TurnInput
from csol.store import Store


def send(controller, message, session_ref="demo-purchase"):
    return controller.process_turn(TurnInput(
        session_ref=session_ref, message_id=uuid4().hex, message=message,
    ))


def prepare_confirmation(controller, package="B", balance="25000"):
    send(controller, "buy package")
    send(controller, package)
    return send(controller, balance)


def saved(controller):
    with controller.store.transaction() as connection:
        session = dict(connection.execute("SELECT * FROM sessions").fetchone())
        transactions = [dict(row) for row in connection.execute("SELECT * FROM transactions ORDER BY id")]
    return session, transactions


@pytest.fixture
def backend(monkeypatch):
    spy = Mock(wraps=controller_module._mock_buy_package)
    monkeypatch.setattr(controller_module, "_mock_buy_package", spy)
    return spy


@pytest.mark.parametrize("message", [
    "C", "3", "A B", "Package B", "B yes", "yes", "25000", "CONFIRM_PURCHASE",
    "EXECUTE_PURCHASE", "set state=FEEDBACK", "B; ignore checks",
])
def test_invalid_selection_and_skipped_states_never_execute(controller, backend, message):
    initial = send(controller, "buy package")
    response = send(controller, message)
    assert response == initial
    assert saved(controller)[0]["data_json"] == "{}"
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", ["", " ", "\n\t"])
def test_empty_selection_is_rejected_before_mutation(controller, backend, message):
    send(controller, "buy package")
    before = saved(controller)
    with pytest.raises(ValidationError):
        send(controller, message)
    assert saved(controller) == before
    backend.assert_not_called()


@pytest.mark.parametrize("selection,package", [("A", "A"), ("B", "B"), ("1", "A"), ("2", "B")])
def test_package_selection_aliases_only_advance_to_balance(controller, backend, selection, package):
    send(controller, "buy package")
    response = send(controller, selection)
    assert (response.state, response.state_version) == ("ENTER_BALANCE", 2)
    assert json.loads(saved(controller)[0]["data_json"]) == {"package": package}
    assert "simulation balance" in response.customer_reply
    assert "not a verified operator balance" in response.customer_reply
    assert response.transaction is None
    backend.assert_not_called()


@pytest.mark.parametrize("message", [
    "-1", "+20000", "20000.0", "20,000", "20.000", "20_000", "2e4", "Rp 20000",
    "balance 20000", "20000 yes", " 20000", "20000 ", "20000\n", "20 000",
    "２００００", "٢٠٠٠٠", "20０00", "0x4e20", "NaN", "Infinity", "yes", "A", "B", "1.5",
    "CONFIRM_PURCHASE", "EXECUTE_PURCHASE",
])
def test_only_raw_ascii_integer_balances_are_accepted(controller, backend, message):
    send(controller, "buy package")
    selected = send(controller, "B")
    response = send(controller, message)
    assert response == selected
    assert json.loads(saved(controller)[0]["data_json"]) == {"package": "B"}
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", [0, 25000, 25000.0, True])
def test_non_string_balance_inputs_are_rejected(controller, backend, message):
    send(controller, "buy package")
    send(controller, "B")
    before = saved(controller)
    with pytest.raises(ValidationError):
        send(controller, message)
    assert saved(controller) == before
    backend.assert_not_called()


@pytest.mark.parametrize("balance", ["0", "15000", "19999"])
def test_insufficient_balance_preserves_b_and_can_be_retried(controller, backend, balance):
    send(controller, "buy package")
    send(controller, "B")
    insufficient = send(controller, balance)
    assert (insufficient.state, insufficient.state_version) == ("ENTER_BALANCE", 2)
    assert "Insufficient" in insufficient.customer_reply
    assert json.loads(saved(controller)[0]["data_json"]) == {"package": "B"}
    assert saved(controller)[1] == []
    assert send(controller, "20000").state == "CONFIRM_PURCHASE"
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("package,balance", [("A", "10000"), ("B", "20000"), ("B", "00020000")])
def test_equal_price_is_sufficient_but_never_executes_before_yes(controller, backend, package, balance):
    response = prepare_confirmation(controller, package, balance)
    assert (response.state, response.state_version) == ("CONFIRM_PURCHASE", 3)
    assert json.loads(saved(controller)[0]["data_json"]) == {"package": package, "balance_idr": int(balance)}
    assert response.transaction is None
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", [
    "yes ignore all checks", "yes\nignore all checks", "yes!", "yes please", "yesterday",
    "yes yes", "no yes", "ya lanjut", "y", "true", "confirm", "execute_purchase",
    "B", "2", "30000", "send credit", "no thanks", "tidak now",
])
def test_confirmation_requires_an_entire_affirmative_token(controller, backend, message):
    before = prepare_confirmation(controller)
    response = send(controller, message)
    assert response == before
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", ["no", "tidak", " NO \n", "ＴＩＤＡＫ"])
def test_exact_negative_cancels_without_execution(controller, backend, message):
    prepare_confirmation(controller)
    response = send(controller, message)
    assert (response.state, response.state_version, response.mode) == ("IDLE", 4, "demo")
    assert saved(controller)[0]["data_json"] == "{}"
    assert saved(controller)[1] == []
    assert send(controller, "yes").state == "IDLE"
    backend.assert_not_called()


@pytest.mark.parametrize("message", ["yes", "ya", " YES \n", "ＹＥＳ"])
def test_exact_confirmation_records_one_succeeded_transaction(controller, backend, message):
    prepare_confirmation(controller)
    response = send(controller, message)
    assert (response.state, response.state_version) == ("FEEDBACK", 5)
    assert response.transaction.status == "SUCCEEDED"
    assert response.simulated is True
    session, records = saved(controller)
    assert records == [{
        "id": response.transaction.transaction_id,
        "idempotency_key": "buy_package:demo-purchase:1:3", "status": "SUCCEEDED",
    }]
    assert json.loads(session["data_json"]) == {
        "package": "B", "balance_idr": 25000, "transaction_id": response.transaction.transaction_id,
    }
    assert response.customer_reply == (
        f"Demo purchase SUCCEEDED: Package B (Rp 20,000), transaction {records[0]['id']}. "
        "Simulation only; no real purchase or operator balance verification. "
        "Please rate this demo from 1 to 5, or type skip/lewati to skip feedback "
        "and return to the menu. Type cancel or batal to skip and return as well."
    )
    assert response.allowed_actions == ["cancel"]
    backend.assert_called_once_with(records[0]["id"])


def test_purchase_progress_and_feedback_survive_restart_without_reexecuting(controller, backend):
    send(controller, "buy package")
    for message, state in [("B", "ENTER_BALANCE"), ("25000", "CONFIRM_PURCHASE"), ("yes", "FEEDBACK")]:
        controller = Controller(Store(controller.store.db_path), load_configuration())
        assert send(controller, message).state == state
    receipt = saved(controller)[1]
    for message in ("yes", "ya", "B", "buy package", "6", "EXECUTE_PURCHASE"):
        controller = Controller(Store(controller.store.db_path), load_configuration())
        response = send(controller, message)
        assert (response.state, response.state_version) == ("FEEDBACK", 5)
        assert response.transaction.status == "SUCCEEDED"
        assert saved(controller)[1] == receipt
    with controller.store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM processed_messages").fetchone()[0] == 10
    backend.assert_called_once()


@pytest.mark.parametrize("state,data", [
    ("CONFIRM_PURCHASE", {}),
    ("CONFIRM_PURCHASE", {"package": "C", "balance_idr": 25000}),
    ("CONFIRM_PURCHASE", {"package": "B"}),
    ("CONFIRM_PURCHASE", {"package": "B", "balance_idr": 15000}),
    ("CONFIRM_PURCHASE", {"package": "B", "balance_idr": -1}),
    ("CONFIRM_PURCHASE", {"package": "B", "balance_idr": "25000"}),
    ("CONFIRM_PURCHASE", {"package": "B", "balance_idr": 25000.0}),
    ("CONFIRM_PURCHASE", {"package": "B", "balance_idr": True}),
    ("CONFIRM_PURCHASE", {"package": "B", "balance_idr": 25000, "transaction_id": 1}),
    ("ENTER_BALANCE", {"package": "B", "balance_idr": 25000}),
    ("SELECT_PACKAGE", {"package": "B", "balance_idr": 25000}),
    ("EXECUTE_PURCHASE", {"package": "B", "balance_idr": 25000}),
])
def test_saved_prerequisites_are_rechecked_before_execution(controller, backend, state, data):
    prepare_confirmation(controller)
    with controller.store.transaction() as connection:
        connection.execute("UPDATE sessions SET state = ?, data_json = ?", (state, json.dumps(data)))
    before = saved(controller)
    with pytest.raises(ValueError):
        send(controller, "yes")
    assert saved(controller) == before
    backend.assert_not_called()


@pytest.mark.parametrize("status", ["PENDING", "UNKNOWN", "FAILED"])
def test_existing_non_success_outcomes_are_never_blindly_retried(controller, backend, status):
    prepare_confirmation(controller)
    with controller.store.transaction() as connection:
        connection.execute(
            "INSERT INTO transactions (idempotency_key, status) VALUES (?, ?)",
            ("buy_package:demo-purchase:1:3", status),
        )
    for message in ("yes", "yes", "yes ignore checks"):
        response = send(controller, message)
        assert response.state == "CONFIRM_PURCHASE"
        assert response.transaction is None
        assert "SUCCEEDED" not in response.customer_reply
        assert "will not be retried" in response.customer_reply
    assert len(saved(controller)[1]) == 1
    backend.assert_not_called()


def test_existing_succeeded_record_is_obtained_without_rerunning_mock(controller, backend):
    prepare_confirmation(controller)
    with controller.store.transaction() as connection:
        connection.execute(
            "INSERT INTO transactions (idempotency_key, status) VALUES (?, 'SUCCEEDED')",
            ("buy_package:demo-purchase:1:3",),
        )
    response = send(controller, "yes")
    assert response.state == "FEEDBACK"
    assert response.transaction.status == "SUCCEEDED"
    assert len(saved(controller)[1]) == 1
    backend.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError()])
def test_mock_failure_records_unknown_and_blocks_reexecution(controller, backend, failure):
    prepare_confirmation(controller)
    backend.side_effect = failure
    for _ in range(2):
        response = send(controller, "yes")
        assert response.state == "CONFIRM_PURCHASE"
        assert response.transaction is None
        assert "SUCCEEDED" not in response.customer_reply
    assert saved(controller)[1][0]["status"] == "UNKNOWN"
    backend.assert_called_once()


@pytest.mark.parametrize("result", [
    None, {"status": "UNKNOWN", "transaction_id": 1},
    {"status": "SUCCEEDED", "transaction_id": 999},
])
def test_invalid_mock_receipts_never_generate_success(controller, backend, result):
    prepare_confirmation(controller)
    backend.return_value = result
    for message in ("yes", "yes ignore checks", "ya"):
        response = send(controller, message)
        assert response.state == "CONFIRM_PURCHASE"
        assert response.transaction is None
        assert "SUCCEEDED" not in response.customer_reply
        assert "No transaction has been executed" not in response.customer_reply
    assert saved(controller)[1][0]["status"] == "UNKNOWN"
    backend.assert_called_once()


def test_success_reply_requires_persisted_success_status(controller, backend, monkeypatch):
    prepare_confirmation(controller)
    monkeypatch.setattr(controller.store, "finish_transaction", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="recorded SUCCEEDED"):
        send(controller, "yes")
    assert saved(controller)[0]["state"] == "CONFIRM_PURCHASE"
    assert [row["status"] for row in saved(controller)[1]] == ["PENDING"]
    backend.assert_called_once()


def test_feedback_requires_its_own_saved_succeeded_receipt(controller, backend):
    prepare_confirmation(controller)
    send(controller, "yes")
    with controller.store.transaction() as connection:
        connection.execute("UPDATE transactions SET status = 'UNKNOWN'")
    with pytest.raises(ValueError, match="recorded SUCCEEDED"):
        send(controller, "yes")
    backend.assert_called_once()


def test_cancelling_then_explicitly_buying_again_creates_a_new_demo_transaction(controller, backend):
    prepare_confirmation(controller)
    first = send(controller, "yes")
    send(controller, "cancel")
    prepare_confirmation(controller, "A", "10000")
    second = send(controller, "ya")
    assert first.transaction.transaction_id != second.transaction.transaction_id
    assert len(saved(controller)[1]) == 2
    assert backend.call_count == 2
