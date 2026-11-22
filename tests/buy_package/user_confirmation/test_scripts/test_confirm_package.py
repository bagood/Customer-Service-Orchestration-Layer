import pytest
from app.model import CONFIRM


@pytest.mark.parametrize("posted,step", [
    ({"outcome": "purchased", "receipt": {"balance": 0}}, "intent_classification"),
    ({"outcome": "insufficient_funds", "shortfall": 30}, "buy_credits_confirmation"),
    ({"outcome": "offer_changed"}, "package_preference_identification"),
])
async def test_accept(enter, call, engine, posted, step):
    await enter(CONFIRM)
    engine.accounts.post.return_value = posted
    result = await call("confirm_package", answer="yes")
    assert result["step"] == step
    assert posted.items() <= result.items()
    assert ("offer" in result["instruction"]["context"]) == (step == "buy_credits_confirmation")


async def test_decline(enter, call, engine):
    await enter(CONFIRM)
    result = await call("confirm_package", answer="no")
    assert result["step"] == "package_preference_identification"
    assert "offer" not in result["instruction"]["context"]
    engine.accounts.post.assert_not_awaited()
