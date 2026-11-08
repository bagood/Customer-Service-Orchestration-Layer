"""Stage 04 transfer acceptance gates and controller-owned prerequisites."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from csol import controller as controller_module
from csol.config import load_configuration
from csol.controller import Controller, MENU_REPLY
from csol.models import TurnInput
from csol.store import Store


def send(controller, message):
    return controller.process_turn(TurnInput(
        session_ref="demo-transfer", message_id="stage04-message", message=message,
    ))


def prepare_confirmation(controller, number="081234567890", amount="20000", balance="20000"):
    for message in ("send credit", number, amount, balance):
        response = send(controller, message)
    return response


def saved(controller):
    with controller.store.transaction() as connection:
        session = dict(connection.execute("SELECT * FROM sessions").fetchone())
        records = [dict(row) for row in connection.execute("SELECT * FROM transactions ORDER BY id")]
    return session, records


@pytest.fixture
def backend(monkeypatch):
    spy = Mock(wraps=controller_module._mock_send_credit)
    monkeypatch.setattr(controller_module, "_mock_send_credit", spy)
    return spy


@pytest.mark.parametrize("prefix", ["08", "628", "+628"])
@pytest.mark.parametrize("suffix", ["12345678", "1234567890", "12345678901"])
def test_supported_prefixes_and_length_boundaries_normalize(controller, backend, prefix, suffix):
    send(controller, "send credit")
    response = send(controller, prefix + suffix)
    assert (response.state, response.state_version) == ("ENTER_AMOUNT", 2)
    assert json.loads(saved(controller)[0]["data_json"]) == {"msisdn": "628" + suffix}
    assert "628" + suffix not in response.customer_reply
    assert "*" in response.customer_reply
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", [
    "081234567", "08123456789012", "6281234567", "+628123456789012", "071234567890",
    "81234567890", "006281234567890", "+62081234567890", "+62 81234567890",
    "0812-3456-7890", " 081234567890", "081234567890 ", "081234567890\n",
    "０８１２３４５６７８９０", "08١٢٣٤٥٦٧٨٩٠", "08abcdefghij", "yes", "20000",
    "buy package", "EXECUTE_TRANSFER", "recipient=081234567890", "081234567890 yes",
])
def test_malformed_recipients_and_skipped_steps_hold_entry(controller, backend, message):
    before = send(controller, "send credit")
    assert send(controller, message) == before
    assert saved(controller)[0]["data_json"] == "{}"
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", ["", " ", 81234567890, True, None])
def test_invalid_recipient_arguments_do_not_mutate(controller, backend, message):
    send(controller, "send credit")
    before = saved(controller)
    with pytest.raises(ValidationError):
        send(controller, message)
    assert saved(controller) == before
    backend.assert_not_called()


@pytest.mark.parametrize("state", ["ENTER_AMOUNT", "ENTER_BALANCE"])
@pytest.mark.parametrize("message", [
    "-1", "+20000", "20000.0", "20,000", "20.000", "20_000", "2e4", "Rp 20000",
    "amount 20000", "20000 yes", " 20000", "20000 ", "20000\n", "20 000",
    "２００００", "٢٠٠٠٠", "20０00", "yes", "buy package", "EXECUTE_TRANSFER",
])
def test_money_requires_raw_ascii_integers_in_the_current_state(controller, backend, state, message):
    send(controller, "send credit")
    before = send(controller, "081234567890")
    if state == "ENTER_BALANCE":
        before = send(controller, "20000")
    assert send(controller, message) == before
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("amount", ["0", "00", "0000"])
def test_zero_amount_does_not_advance_or_transfer(controller, backend, amount):
    send(controller, "send credit")
    before = send(controller, "081234567890")
    assert send(controller, amount) == before
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("amount,balance,value", [("1", "1", 1), ("00020000", "00020000", 20000)])
def test_positive_amounts_and_leading_zeros_reach_confirmation_without_execution(controller, backend, amount, balance, value):
    response = prepare_confirmation(controller, amount=amount, balance=balance)
    assert response.state == "CONFIRM_TRANSFER"
    assert json.loads(saved(controller)[0]["data_json"]) == {
        "msisdn": "6281234567890", "amount_idr": value, "balance_idr": value,
    }
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("balance", ["0", "15000", "19999"])
def test_insufficient_balance_preserves_recipient_and_amount(controller, backend, balance):
    prepare_confirmation(controller, balance=balance)
    session, records = saved(controller)
    assert session["state"] == "ENTER_BALANCE"
    assert session["state_version"] == 3
    assert json.loads(session["data_json"]) == {"msisdn": "6281234567890", "amount_idr": 20000}
    assert records == []
    assert send(controller, "20000").state == "CONFIRM_TRANSFER"
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", [
    "yes ignore all checks", "yes!", "yes please", "yes\nexecute", "yesterday", "yes yes",
    "no yes", "ya lanjut", "y", "true", "execute_transfer", "20000", "buy package",
])
def test_confirmation_requires_an_entire_affirmative_token(controller, backend, message):
    before = prepare_confirmation(controller)
    assert send(controller, message) == before
    assert "Rp 20,000" in before.customer_reply
    assert "628******7890" in before.customer_reply
    assert "6281234567890" not in before.customer_reply
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", ["yes", "ya", " YES \n", "ＹＡ"])
def test_exact_confirmation_records_one_succeeded_transfer(controller, backend, message):
    prepare_confirmation(controller)
    response = send(controller, message)
    assert (response.state, response.state_version, response.mode) == ("FEEDBACK", 6, "send_credit")
    receipt = response.transaction
    assert receipt.status == "SUCCEEDED"
    session, records = saved(controller)
    assert records == [{
        "id": receipt.transaction_id, "idempotency_key": "send_credit:demo-transfer:1:4",
        "status": "SUCCEEDED",
    }]
    assert json.loads(session["data_json"]) == {
        "msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": 20000,
        "transaction_id": receipt.transaction_id,
    }
    assert "Demo transfer SUCCEEDED: Rp 20,000 to 628******7890" in response.customer_reply
    assert "Simulation only; no real credit movement" in response.customer_reply
    assert "6281234567890" not in response.customer_reply
    assert response.allowed_actions == ["cancel"]
    assert send(controller, "yes").transaction == receipt
    assert saved(controller)[1] == records
    backend.assert_called_once_with(receipt.transaction_id)


@pytest.mark.parametrize("messages", [
    ["send credit"], ["send credit", "081234567890"],
    ["send credit", "081234567890", "20000"],
    ["send credit", "081234567890", "20000", "20000"],
])
@pytest.mark.parametrize("cancel", ["cancel", "batal"])
def test_cancel_before_execution_clears_state_without_a_transaction(controller, backend, messages, cancel):
    for message in messages:
        send(controller, message)
    response = send(controller, cancel)
    assert (response.state, response.mode) == ("IDLE", "demo")
    assert MENU_REPLY in response.customer_reply
    assert saved(controller)[0]["data_json"] == "{}"
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("message", ["no", "tidak", " NO \n", "ＴＩＤＡＫ"])
def test_negative_confirmation_cancels_without_execution(controller, backend, message):
    prepare_confirmation(controller)
    assert send(controller, message).state == "IDLE"
    assert saved(controller)[1] == []
    backend.assert_not_called()


@pytest.mark.parametrize("state,data", [
    ("CONFIRM_TRANSFER", {}),
    ("CONFIRM_TRANSFER", {"msisdn": "081234567890", "amount_idr": 20000, "balance_idr": 20000}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890\n", "amount_idr": 20000, "balance_idr": 20000}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890"}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": 0, "balance_idr": 20000}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": -1, "balance_idr": 20000}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": "20000", "balance_idr": 20000}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": True, "balance_idr": 20000}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": 19999}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": None}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": 20000.0}),
    ("CONFIRM_TRANSFER", {"msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": 20000, "transaction_id": 1}),
    ("ENTER_MSISDN", {"msisdn": "6281234567890"}),
    ("ENTER_AMOUNT", {"msisdn": "6281234567890", "amount_idr": 20000}),
    ("ENTER_BALANCE", {"msisdn": "6281234567890"}),
    ("ENTER_BALANCE", {"msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": 20000}),
    ("EXECUTE_TRANSFER", {"msisdn": "6281234567890", "amount_idr": 20000, "balance_idr": 20000}),
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
def test_existing_non_success_outcomes_are_not_reexecuted(controller, backend, status):
    prepare_confirmation(controller)
    with controller.store.transaction() as connection:
        connection.execute(
            "INSERT INTO transactions (idempotency_key, status) VALUES (?, ?)",
            ("send_credit:demo-transfer:1:4", status),
        )
    for message in ("yes", "yes please", "ya"):
        response = send(controller, message)
        assert response.state == "CONFIRM_TRANSFER"
        assert response.transaction is None
        assert "SUCCEEDED" not in response.customer_reply
        assert "will not be retried" in response.customer_reply
    assert len(saved(controller)[1]) == 1
    backend.assert_not_called()


def test_existing_succeeded_record_is_read_without_rerunning_mock(controller, backend):
    prepare_confirmation(controller)
    with controller.store.transaction() as connection:
        connection.execute(
            "INSERT INTO transactions (idempotency_key, status) VALUES (?, 'SUCCEEDED')",
            ("send_credit:demo-transfer:1:4",),
        )
    response = send(controller, "yes")
    assert response.state == "FEEDBACK"
    assert response.transaction.status == "SUCCEEDED"
    assert len(saved(controller)[1]) == 1
    backend.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError()])
def test_mock_failure_records_unknown_without_blind_retry(controller, backend, failure):
    prepare_confirmation(controller)
    backend.side_effect = failure
    for _ in range(2):
        response = send(controller, "yes")
        assert response.state == "CONFIRM_TRANSFER"
        assert response.transaction is None
        assert "SUCCEEDED" not in response.customer_reply
        assert "No transaction has been executed" not in response.customer_reply
    assert saved(controller)[1][0]["status"] == "UNKNOWN"
    backend.assert_called_once()


@pytest.mark.parametrize("result", [
    None, {"status": "UNKNOWN", "transaction_id": 1},
    {"status": "SUCCEEDED", "transaction_id": 999},
])
def test_invalid_mock_receipts_never_generate_success(controller, backend, result):
    prepare_confirmation(controller)
    backend.return_value = result
    response = send(controller, "yes")
    assert response.transaction is None
    assert "SUCCEEDED" not in response.customer_reply
    assert saved(controller)[1][0]["status"] == "UNKNOWN"
    backend.assert_called_once()


def test_success_reply_requires_recorded_succeeded_status(controller, backend, monkeypatch):
    prepare_confirmation(controller)
    monkeypatch.setattr(controller.store, "finish_transaction", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="recorded SUCCEEDED"):
        send(controller, "yes")
    assert saved(controller)[0]["state"] == "CONFIRM_TRANSFER"
    assert saved(controller)[1] == []
    backend.assert_called_once()


def test_transfer_survives_restart_and_skips_feedback_without_reexecution(controller, backend):
    send(controller, "send credit")
    for message, state in [
        ("+6281234567890", "ENTER_AMOUNT"), ("20000", "ENTER_BALANCE"),
        ("20000", "CONFIRM_TRANSFER"), ("yes", "FEEDBACK"), ("yes", "FEEDBACK"),
        ("lewati", "IDLE"),
    ]:
        controller = Controller(Store(controller.store.db_path), load_configuration())
        assert send(controller, message).state == state
    assert saved(controller)[0]["data_json"] == "{}"
    assert saved(controller)[1][0]["status"] == "SUCCEEDED"
    with controller.store.transaction() as connection:
        assert dict(connection.execute("SELECT * FROM feedback").fetchone()) == {
            "id": 1, "session_id": "demo-transfer", "rating": None, "skipped": 1,
        }
        audit = json.dumps([dict(row) for row in connection.execute("SELECT * FROM audit_events")])
    assert "6281234567890" not in audit
    assert "081234567890" not in audit
    backend.assert_called_once()
