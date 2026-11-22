import pytest
from app.engine import allowed
from app.store import BindingMismatch


async def test_independent_chats_bound_to_one_account(engine, call):
    first = await engine.invoke("chat", "wallet", "identification_instruction", {}, turn="first")
    assert "name" in first["instruction"]["question"]
    engine.accounts.post.return_value = {"outcome": "name_recorded"}
    result = await call("record_name", name=" Ari ")
    assert (result["state"], result["step"]) == ("landing", "intent_classification")
    assert result["instruction"]["context"]["display_name"] == "Ari"
    other = await engine.conversations.read("other", "wallet")
    assert other.revision == 0 and "record_name" in allowed(other)
    assert (await call("record_name", name="Ari"))["outcome"] == "out_of_step"
    with pytest.raises(BindingMismatch):
        await engine.conversations.read("chat", "different-wallet")


async def test_invalid_name(engine, call):
    assert (await call("record_name", name="  "))["outcome"] == "invalid_input"
    engine.accounts.post.assert_not_awaited()
