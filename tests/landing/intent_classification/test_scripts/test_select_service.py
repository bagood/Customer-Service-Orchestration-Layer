import pytest
from conftest import MENU, PREFERENCES, CREDITS


@pytest.mark.parametrize("service,destination", [("buy_package", PREFERENCES), ("buy_credits", CREDITS), ("unclear", MENU)])
async def test_menu(enter, call, service, destination):
    await enter(MENU)
    result = await call("select_service", service=service)
    assert (result["state"], result["step"]) == destination
