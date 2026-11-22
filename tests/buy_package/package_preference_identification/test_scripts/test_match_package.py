from app.model import PREFERENCES
from conftest import OFFER


async def test_match_and_revise(enter, call, engine):
    await enter(PREFERENCES)
    assert (await call("match_package"))["outcome"] == "clarify_preferences"
    engine.accounts.match.return_value = None
    assert (await call("match_package", 1, benefit="roaming"))["outcome"] == "no_match"
    engine.accounts.match.return_value = OFFER
    result = await call("match_package", 2, benefit="streaming", min_quota_gb=4, max_price=50)
    engine.accounts.match.assert_awaited_with("streaming", 4, 50)
    assert result["instruction"]["context"]["offer"] == OFFER
    assert result["step"] == "user_confirmation"
