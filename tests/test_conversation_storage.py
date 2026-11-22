import asyncio
import json
from copy import deepcopy

import pytest

from app.engine import Engine
from app.registry import WorkflowAccess
from app.store import Conversations, InvalidConversation
from conftest import CONFIRM, CREDITS, LEGACY_TOOLS, MENU, OFFER, START

KEY = "csol:conversation:chat"


def legacy_record(position=MENU, **changes):
    return {
        "customer": "wallet", "instance": "stable-instance", "state": position[0], "step": position[1],
        "revision": 4, "display_name": "Ari", "offer": OFFER, "offer_presented_turn": "turn-original",
        "shortfall": 30, "return_question": None, "in_flight": None, **changes,
    }


@pytest.mark.parametrize("pair", LEGACY_TOOLS)
async def test_legacy_records_convert_on_successful_action(engine, pair):
    store = engine.conversations
    raw = json.dumps(legacy_record(pair), indent=2)
    await store.redis.set(KEY, raw)

    result = await engine.invoke("chat", "wallet", LEGACY_TOOLS[pair][0], {}, turn="read")
    assert result["allowed_tools"] == [*LEGACY_TOOLS[pair], *engine.registry.global_actions]
    assert result["instruction"]["context"] == {"display_name": "Ari", "offer": OFFER, "shortfall": 30}
    assert await store.redis.get(KEY) == raw

    await engine.invoke("chat", "wallet", "request_return_to_landing", {"revision": 4}, turn="request")
    restarted = Conversations(store.redis, engine.registry, "versioned")
    c = await restarted.read("chat", "wallet")
    stored = json.loads(await store.redis.get(KEY))
    assert stored["version"] == 1
    assert (c.position, c.instance, c.customer, c.revision) == (pair, "stable-instance", "wallet", 5)
    assert c.return_question == {"state": pair[0], "step": pair[1], "revision": 5, "turn": "request"}


async def test_compatibility_switch_and_rollback(engine):
    redis, registry = engine.conversations.redis, engine.registry
    legacy_store = Conversations(redis, registry)
    compatibility = Engine(legacy_store, engine.accounts, registry)
    await redis.set(KEY, json.dumps(legacy_record(START, offer=None, shortfall=None)))
    engine.accounts.post.return_value = {"outcome": "name_recorded"}
    await compatibility.invoke("chat", "wallet", "record_name", {"revision": 4, "name": "Aria"}, turn="name")
    assert "version" not in json.loads(await redis.get(KEY))

    pending = await engine.invoke("chat", "wallet", "request_return_to_landing", {"revision": 5}, turn="request")
    assert pending["revision"] == 6
    versioned = await redis.get(KEY)
    assert json.loads(versioned)["version"] == 1
    read_after_rollback = await legacy_store.read("chat", "wallet")
    assert read_after_rollback.return_question["turn"] == "request"
    assert await redis.get(KEY) == versioned

    resolved = await compatibility.invoke("chat", "wallet", "resolve_return_to_landing",
                                          {"revision": 6, "answer": "no"}, turn="decline")
    flat = json.loads(await redis.get(KEY))
    assert "version" not in flat and flat["revision"] == 7
    assert resolved["instruction"]["context"]["display_name"] == "Aria"


async def test_replay_legacy_reservation_uses_original_turn(engine):
    reservation = {"tool": "add_credits", "arguments": {"revision": 4, "amount": 30}, "turn": "reserved"}
    raw = json.dumps(legacy_record(CREDITS, in_flight=reservation))
    await engine.conversations.redis.set(KEY, raw)
    result = await engine.invoke("chat", "wallet", "credit_instruction", {}, turn="later")
    assert result["instruction"]["context"]["recorded_arguments"] == reservation["arguments"]
    assert await engine.conversations.redis.get(KEY) == raw

    engine.accounts.post.return_value = {"outcome": "credited"}
    result = await engine.invoke("chat", "wallet", "add_credits", reservation["arguments"], turn="later")
    assert (result["state"], result["step"]) == CONFIRM
    c = await engine.conversations.read("chat", "wallet")
    assert WorkflowAccess(engine.registry, c, "buy_package").context()["offer_presented_turn"] == "reserved"
    assert c.in_flight is None and c.revision == 5


@pytest.mark.parametrize("changes", [
    {"version": 2},
    {"step": "missing"},
    {"revision": True},
    {"display_name": 123},
    {"offer": {**OFFER, "price": 0}},
    {"offer": {**OFFER, "extra": True}},
    {"return_question": {"state": MENU[0], "step": MENU[1], "revision": 3, "turn": "old"}},
    {"in_flight": {"tool": "confirm_package", "arguments": {"revision": 4, "answer": "yes"}, "turn": "x"}},
])
async def test_invalid_legacy_records_survive_read_failure(engine, changes):
    store = engine.conversations
    raw = json.dumps(legacy_record(**changes))
    await store.redis.set(KEY, raw)
    with pytest.raises(InvalidConversation):
        await store.read("chat", "wallet")
    assert await store.redis.get(KEY) == raw


async def test_versioned_record_rejects_extra_context(engine):
    raw = json.dumps({
        "customer": "wallet", "instance": "fixture", "state": MENU[0], "step": MENU[1],
        "revision": 4, "version": 1, "context": {"start": {"private": "value"}},
    })
    store = engine.conversations
    await store.redis.set(KEY, raw)
    with pytest.raises(InvalidConversation, match="unknown context field start.private"):
        await store.read("chat", "wallet")
    assert await store.redis.get(KEY) == raw


async def test_two_writers_share_the_original_legacy_snapshot(engine):
    store = engine.conversations
    await store.redis.set(KEY, json.dumps(legacy_record(), indent=4))
    first, second = await asyncio.gather(store.read("chat", "wallet"), store.read("chat", "wallet"))
    changes = [deepcopy(first), deepcopy(second)]
    for updated in changes:
        updated.revision += 1
    outcomes = await asyncio.gather(store.replace("chat", first, changes[0]), store.replace("chat", second, changes[1]))
    assert sorted(outcomes) == [False, True]
    assert (await store.read("chat", "wallet")).revision == 5
