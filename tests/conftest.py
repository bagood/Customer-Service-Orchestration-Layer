import json
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from app.engine import Engine
from app.registry import build_registry
from app.store import Conversations

OFFER = {"package_id": "p", "name": "Data", "benefits": "streaming", "quota_gb": 5, "price": 50}
START = ("start", "identification")
MENU = ("landing", "intent_classification")
PREFERENCES = ("buy_package", "package_preference_identification")
CONFIRM = ("buy_package", "user_confirmation")
DETOUR = ("buy_package", "buy_credits_confirmation")
CREDITS = ("buy_credits", "amount_of_balance")

STEP_TOOLS = {
    START: ("identification_instruction", "record_name"),
    MENU: ("menu_instruction", "select_service"),
    PREFERENCES: ("preference_instruction", "match_package"),
    CONFIRM: ("purchase_instruction", "confirm_package"),
    DETOUR: ("detour_instruction", "confirm_credit_detour"),
    CREDITS: ("credit_instruction", "add_credits"),
}


@pytest.fixture(scope="session")
def registry():
    return build_registry()


@pytest.fixture
async def engine(registry):
    async with FakeRedis(decode_responses=True) as redis:
        yield Engine(Conversations(redis, registry), AsyncMock(), registry)


@pytest.fixture
def enter(engine):
    async def seed(pair, *, display_name=None, **package_context):
        if pair in (CONFIRM, DETOUR):
            package_context.setdefault("offer", OFFER)
        data = {
            "version": 1, "customer": "wallet", "instance": "fixture", "state": pair[0], "step": pair[1],
            "revision": 0, "context": {"start": {"display_name": display_name}, "buy_package": package_context},
        }
        await engine.conversations.redis.set("csol:conversation:chat", json.dumps(data))
    return seed


@pytest.fixture
def call(engine):
    async def invoke(tool, revision=0, turn=None, **arguments):
        return await engine.invoke("chat", "wallet", tool, {"revision": revision, **arguments}, turn=turn or f"turn-{revision}")
    return invoke
