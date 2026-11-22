import asyncio
import json
from copy import deepcopy

import pytest

from app.registry import WorkflowAccess
from app.store import Conversations, InvalidConversation
from conftest import CONFIRM, CREDITS, STEP_TOOLS, MENU, OFFER

KEY = "csol:conversation:chat"


def conversation_record(position=MENU, **changes):
    return {
        "customer": "wallet", "instance": "stable-instance", "state": position[0], "step": position[1],
        "version": 1, "revision": 4, "return_question": None, "in_flight": None,
        "context": {
            "start": {"display_name": "Ari"},
            "buy_package": {"offer": OFFER, "offer_presented_turn": "turn-original", "shortfall": 30},
        },
        **changes,
    }


async def test_new_conversation_starts_with_the_envelope(engine):
    store = engine.conversations
    c = await store.read("chat", "wallet")
    assert json.loads(await store.redis.get(KEY)) == {
        "version": 1,
        "customer": "wallet",
        "instance": c.instance,
        "state": engine.registry.start[0],
        "step": engine.registry.start[1],
        "revision": 0,
        "context": {},
        "return_question": None,
        "in_flight": None,
    }


@pytest.mark.parametrize("pair", STEP_TOOLS)
async def test_conversation_records_resume_at_each_step(engine, pair):
    store = engine.conversations
    raw = json.dumps(conversation_record(pair), indent=2)
    await store.redis.set(KEY, raw)

    result = await engine.invoke("chat", "wallet", STEP_TOOLS[pair][0], {}, turn="read")
    assert result["allowed_tools"] == [*STEP_TOOLS[pair], *engine.registry.global_actions]
    assert result["instruction"]["context"] == {"display_name": "Ari", "offer": OFFER, "shortfall": 30}
    assert await store.redis.get(KEY) == raw

    await engine.invoke("chat", "wallet", "request_return_to_landing", {"revision": 4}, turn="request")
    restarted = Conversations(store.redis, engine.registry)
    c = await restarted.read("chat", "wallet")
    stored = json.loads(await store.redis.get(KEY))
    assert stored["version"] == 1
    assert (c.position, c.instance, c.customer, c.revision) == (pair, "stable-instance", "wallet", 5)
    assert c.return_question == {"state": pair[0], "step": pair[1], "revision": 5, "turn": "request"}


async def test_replay_reservation_uses_original_turn(engine):
    reservation = {"tool": "add_credits", "arguments": {"revision": 4, "amount": 30}, "turn": "reserved"}
    raw = json.dumps(conversation_record(CREDITS, in_flight=reservation))
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
    {"version": True},
    {"step": "missing"},
    {"revision": True},
    {"context": {"start": {"display_name": 123}}},
    {"context": {"buy_package": {"offer": {**OFFER, "price": 0}}}},
    {"context": {"buy_package": {"offer": {**OFFER, "extra": True}}}},
    {"return_question": {"state": MENU[0], "step": MENU[1], "revision": 3, "turn": "old"}},
    {"in_flight": {"tool": "confirm_package", "arguments": {"revision": 4, "answer": "yes"}, "turn": "x"}},
])
async def test_invalid_conversation_records_survive_read_failure(engine, changes):
    store = engine.conversations
    raw = json.dumps(conversation_record(**changes))
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


async def test_two_writers_share_the_original_snapshot(engine):
    store = engine.conversations
    await store.redis.set(KEY, json.dumps(conversation_record(), indent=4))
    first, second = await asyncio.gather(store.read("chat", "wallet"), store.read("chat", "wallet"))
    changes = [deepcopy(first), deepcopy(second)]
    for updated in changes:
        updated.revision += 1
    outcomes = await asyncio.gather(store.replace("chat", first, changes[0]), store.replace("chat", second, changes[1]))
    assert sorted(outcomes) == [False, True]
    assert (await store.read("chat", "wallet")).revision == 5
