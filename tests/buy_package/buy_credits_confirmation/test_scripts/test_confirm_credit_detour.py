import pytest
from conftest import DETOUR


@pytest.mark.parametrize("answer,step,keep", [("yes", "amount_of_balance", True), ("no", "intent_classification", False)])
async def test_credit_detour(enter, call, answer, step, keep):
    await enter(DETOUR, shortfall=30)
    result = await call("confirm_credit_detour", answer=answer)
    assert result["step"] == step
    assert ("offer" in result["instruction"]["context"]) == keep
