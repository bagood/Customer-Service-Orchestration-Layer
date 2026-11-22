import pytest
from conftest import CREDITS
from conftest import OFFER


@pytest.mark.parametrize("offer,destination", [(None, "intent_classification"), (OFFER, "user_confirmation")])
async def test_credit_destinations(engine, enter, call, offer, destination):
    await enter(CREDITS, offer=offer)
    engine.accounts.post.return_value = {"outcome": "credited", "receipt": {"change": 30, "balance": 50}}
    result = await call("add_credits", amount=30)
    assert result["receipt"]["balance"] == 50 and result["step"] == destination
    assert engine.accounts.post.await_count == 1


@pytest.mark.parametrize("amount", [0, -5, 1.5, True, "5", 2**31])
async def test_invalid_amount(engine, enter, call, amount):
    await enter(CREDITS)
    assert (await call("add_credits", amount=amount))["outcome"] == "invalid_input"
    engine.accounts.post.assert_not_awaited()
