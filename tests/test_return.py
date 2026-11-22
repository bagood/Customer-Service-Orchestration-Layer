import pytest
from app.engine import STEPS
from app.model import MENU


@pytest.mark.parametrize("pair", STEPS)
@pytest.mark.parametrize("answer", ["yes", "no"])
async def test_return_at_every_step(engine, enter, call, pair, answer):
    await enter(pair, display_name="Ari")
    before = await engine.conversations.read("chat", "wallet")
    assert (await call("resolve_return_to_landing", answer="yes"))["outcome"] == "no_pending_return"
    pending = await call("request_return_to_landing")
    assert pending["allowed_tools"] == [*STEPS[pair].names, "request_return_to_landing", "resolve_return_to_landing"]
    assert "leave" in pending["instruction"]["question"]
    assert (await call("resolve_return_to_landing", 0, answer="yes"))["outcome"] == "stale_revision"
    result = await call("resolve_return_to_landing", 1, answer=answer)
    expected = MENU if answer == "yes" else pair
    assert (result["state"], result["step"]) == expected
    after = await engine.conversations.read("chat", "wallet")
    assert after.offer == (None if answer == "yes" else before.offer)
    assert after.display_name == "Ari" and after.return_question is None


async def test_return_answer_cannot_purchase(engine, enter, call):
    from app.model import CONFIRM
    await enter(CONFIRM)
    await call("request_return_to_landing")
    premature = await call("resolve_return_to_landing", 1, turn="turn-0", answer="yes")
    assert premature["outcome"] == "await_fresh_confirmation" and premature["revision"] == 1
    result = await call("confirm_package", 1, answer="yes")
    assert result["outcome"] == "return_pending"
    assert result["instruction"]["action"] == "resolve_return_to_landing"
    engine.accounts.post.assert_not_awaited()
    ambiguous = await call("resolve_return_to_landing", 1, answer="unclear")
    assert ambiguous["instruction"]["action"] == "resolve_return_to_landing"
    assert (await call("resolve_return_to_landing", 2, answer="no"))["step"] == "user_confirmation"
