import json
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from app.engine import Engine
from app.model import Conversation, CONFIRM, DETOUR
from app.store import Conversations

OFFER = {"package_id": "p", "name": "Data", "benefits": "streaming", "quota_gb": 5, "price": 50}


@pytest.fixture
async def engine():
    async with FakeRedis(decode_responses=True) as redis:
        yield Engine(Conversations(redis), AsyncMock())


@pytest.fixture
def enter(engine):
    async def seed(pair, **context):
        c = Conversation(customer="wallet", state=pair[0], step=pair[1], **context)
        if pair in (CONFIRM, DETOUR):
            c.offer = OFFER
        await engine.conversations.redis.set("csol:conversation:chat", json.dumps(c.dump()))
        return c
    return seed


@pytest.fixture
def call(engine):
    async def invoke(tool, revision=0, turn=None, **arguments):
        return await engine.invoke("chat", "wallet", tool, {"revision": revision, **arguments}, turn=turn or f"turn-{revision}")
    return invoke
