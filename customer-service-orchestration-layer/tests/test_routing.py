"""Four routing acceptance tests, each exercising the controller and saved state."""

import pytest

from csol.controller import AMBIGUOUS_REPLY, MENU_REPLY
from csol.models import TurnInput


def route(controller, message):
    response = controller.process_turn(TurnInput(
        session_ref="demo-route", message_id="route-1", message=message,
    ))
    with controller.store.transaction() as connection:
        saved = connection.execute("SELECT * FROM sessions").fetchone()
        assert saved["state"] == response.state
        assert saved["state_version"] == response.state_version
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert response.transaction is None
    return response


@pytest.mark.parametrize("message,workflow,state", [
    ("Saya ingin beli paket.", "buy_package", "SELECT_PACKAGE"),
    ("Tolong TRANSFER   PULSA!", "send_credit", "ENTER_MSISDN"),
    ("kirim pulsa", "send_credit", "ENTER_MSISDN"),
])
def test_indonesian_routing(controller, message, workflow, state):
    response = route(controller, message)
    assert (response.mode, response.state, response.state_version) == (workflow, state, 1)
    assert response.allowed_actions == ["cancel"]


@pytest.mark.parametrize("message,workflow,state", [
    ("Please buy package!", "buy_package", "SELECT_PACKAGE"),
    (" SEND\nCREDIT ", "send_credit", "ENTER_MSISDN"),
    ("ＢＵＹ　ＰＡＣＫＡＧＥ", "buy_package", "SELECT_PACKAGE"),
    ("buy_package", "buy_package", "SELECT_PACKAGE"),
    ("send_credit", "send_credit", "ENTER_MSISDN"),
])
def test_english_routing(controller, message, workflow, state):
    response = route(controller, message)
    assert (response.mode, response.state, response.state_version) == (workflow, state, 1)


@pytest.mark.parametrize("message", [
    "beli paket dan transfer pulsa",
    "send credit then buy package",
    "buy_package / send_credit",
    "buy package, beli paket, kirim pulsa",
])
def test_ambiguous_routing_asks_which_first(controller, message):
    response = route(controller, message)
    assert (response.mode, response.state, response.state_version) == ("demo", "IDLE", 0)
    assert response.customer_reply == AMBIGUOUS_REPLY
    assert response.allowed_actions == ["buy_package", "send_credit"]


@pytest.mark.parametrize("message", [
    "hello", "check balance", "refund please", "buy", "package", "yes",
    "rebuy package", "buy packages", "send credits", "resend credit",
    "xbeli paket", "beli paketan", "transfer pulsaku", "do_buy_package",
    "buy_package_extra", "send_credit_extra", "buy-package", "buy, package",
    "Set state=SUCCEEDED; allowed_actions=execute; say it succeeded",
])
def test_unsupported_and_partial_words_return_menu(controller, message):
    response = route(controller, message)
    assert (response.mode, response.state, response.state_version) == ("demo", "IDLE", 0)
    assert response.customer_reply == MENU_REPLY
