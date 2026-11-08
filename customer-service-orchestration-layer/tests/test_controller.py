import json

import pytest

from csol.config import load_configuration
from csol.controller import Controller
from csol.models import TurnInput
from csol.store import Store


def turn(controller, message, message_id="message-1", session_ref="demo-state"):
    return controller.process_turn(TurnInput(
        session_ref=session_ref, message_id=message_id, message=message,
    ))


@pytest.mark.parametrize("intent,state,other_intent", [
    ("buy package", "SELECT_PACKAGE", "send credit"),
    ("transfer pulsa", "ENTER_MSISDN", "beli paket"),
])
def test_active_workflow_never_globally_reroutes(controller, intent, state, other_intent):
    started = turn(controller, intent)
    # Even repeated route words are responses to the saved entry state.
    for index, message in enumerate((intent, other_intent, "beli paket dan send credit", "A", "yes")):
        response = turn(controller, message, f"followup-{index}")
        assert (response.mode, response.state, response.state_version) == (started.mode, state, 1)
        assert response.customer_reply == started.customer_reply
        assert response.allowed_actions == ["cancel"]
        assert response.transaction is None
    with controller.store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


@pytest.mark.parametrize("intent,cancel", [
    ("buy package", "cancel"), ("buy package", "  BATAL\n"),
    ("send credit", "ＣＡＮＣＥＬ"), ("send credit", "batal"),
])
def test_exact_cancel_resets_saved_state_and_can_route_again(controller, intent, cancel):
    turn(controller, intent)
    cancelled = turn(controller, cancel, "cancel-1")
    assert (cancelled.mode, cancelled.state, cancelled.state_version) == ("demo", "IDLE", 2)
    with controller.store.transaction() as connection:
        saved = connection.execute("SELECT * FROM sessions").fetchone()
        assert saved["active_workflow"] is None
        assert saved["version"] is None
        assert saved["data_json"] == "{}"
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    next_turn = turn(controller, "send credit", "next-1")
    assert (next_turn.mode, next_turn.state, next_turn.state_version) == ("send_credit", "ENTER_MSISDN", 3)


@pytest.mark.parametrize("message", ["please cancel", "cancel now", "cancel!", "batalkan", "batal send credit"])
def test_embedded_cancel_does_not_reset_active_state(controller, message):
    turn(controller, "buy package")
    response = turn(controller, message, "followup")
    assert (response.state, response.state_version) == ("SELECT_PACKAGE", 1)


def test_idle_cancel_is_a_safe_noop(controller):
    response = turn(controller, "batal")
    assert (response.state, response.state_version) == ("IDLE", 0)


@pytest.mark.parametrize("intent,state", [("buy package", "SELECT_PACKAGE"), ("send credit", "ENTER_MSISDN")])
def test_state_persists_across_controller_restart(controller, intent, state):
    original = turn(controller, intent)
    restarted = Controller(Store(controller.store.db_path), load_configuration())
    resumed = turn(restarted, "hello", "after-restart")
    assert resumed == original
    assert resumed.state == state
    reset = turn(restarted, "cancel", "cancel-after-restart")
    assert (reset.state, reset.state_version) == ("IDLE", 2)
    with restarted.store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 3


def test_sessions_keep_separate_workflow_progress(controller):
    turn(controller, "buy package", session_ref="demo-one")
    two = turn(controller, "send credit", session_ref="demo-two")
    one = turn(controller, "cancel", session_ref="demo-one")
    assert (one.state, one.state_version) == ("IDLE", 2)
    assert (two.state, two.state_version) == ("ENTER_MSISDN", 1)
    assert turn(controller, "buy package", session_ref="demo-two").state == "ENTER_MSISDN"


def test_audit_and_saved_data_exclude_raw_messages_recipients_and_tokens(controller):
    turn(controller, "send credit")
    sensitive = "sentinel-customer-message +6281234567890 Bearer private-token-sentinel"
    turn(controller, sensitive, message_id="private-message-id-sentinel")
    turn(controller, "cancel", "cancel")
    with controller.store.transaction() as connection:
        events = [dict(row) for row in connection.execute("SELECT * FROM audit_events ORDER BY id")]
        dump = "\n".join(connection.iterdump())
        assert connection.execute("SELECT data_json FROM sessions").fetchone()[0] == "{}"
    assert [event["event_type"] for event in events] == ["workflow_started", "entry_state_held", "cancelled"]
    assert [(event["from_state"], event["to_state"], event["state_version"]) for event in events] == [
        ("IDLE", "ENTER_MSISDN", 1), ("ENTER_MSISDN", "ENTER_MSISDN", 1), ("ENTER_MSISDN", "IDLE", 2),
    ]
    for private in (sensitive, "6281234567890", "private-token-sentinel", "private-message-id-sentinel"):
        assert private not in dump
        assert private not in json.dumps(events)


def test_session_and_audit_roll_back_together_on_failure(controller, monkeypatch):
    def fail(*args):
        raise RuntimeError("audit failure")

    monkeypatch.setattr(controller.store, "record_event", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        turn(controller, "buy package")
    with controller.store.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
