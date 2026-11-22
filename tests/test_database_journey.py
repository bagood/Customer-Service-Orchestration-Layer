"""Set both CSOL_TEST URLs to run against dedicated databases with the fixture schema."""
import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest
from redis.asyncio import Redis

from app.database import Accounts
from app.engine import Engine
from conftest import CONFIRM, CREDITS, MENU
from app.store import Conversations


@pytest.fixture
async def live(registry):
    pg_url = os.getenv("CSOL_TEST_DATABASE_URL")
    redis_url = os.getenv("CSOL_TEST_REDIS_URL")
    if not (pg_url and redis_url):
        pytest.skip("Set CSOL_TEST_DATABASE_URL and CSOL_TEST_REDIS_URL for the PostgreSQL and Redis checks")
    customer = "test-" + uuid4().hex
    async with asyncpg.create_pool(pg_url, min_size=1, max_size=4) as pool, Redis.from_url(redis_url) as redis:
        await pool.execute("INSERT INTO csol.customers(customer_id,balance) VALUES ($1,20)", customer)
        try:
            await pool.execute("INSERT INTO csol.packages VALUES ($1,'Demo',$1,5,50)", customer)
            yield Engine(Conversations(redis, registry, "versioned"), Accounts(pool), registry), customer, pool
        finally:
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("DELETE FROM csol.operations WHERE customer_id=$1", customer)
                await conn.execute("DELETE FROM csol.customers WHERE customer_id=$1", customer)
                await conn.execute("DELETE FROM csol.packages WHERE package_id=$1", customer)
            await redis.delete(f"csol:conversation:{customer}", f"csol:conversation:{customer}-other")


async def test_purchase_detour_and_commit_recovery(live, monkeypatch):
    engine, customer, pool = live
    redis, registry = engine.conversations.redis, engine.registry
    engine = Engine(Conversations(redis, registry), engine.accounts, registry)

    async def act(tool, rev, **args):
        return await engine.invoke(customer, customer, tool, {"revision": rev, **args}, turn=str(rev))

    assert (await act("record_name", 0, name="Ari"))["outcome"] == "name_recorded"
    await act("select_service", 1, service="buy_package")
    assert (await act("match_package", 2, benefit=customer, min_quota_gb=6))["outcome"] == "no_match"
    assert (await act("match_package", 3, benefit=customer, max_price=49))["outcome"] == "no_match"
    await act("match_package", 4, benefit=customer, min_quota_gb=5, max_price=50)
    assert (await act("confirm_package", 5, answer="yes"))["shortfall"] == 30
    await act("confirm_credit_detour", 6, answer="yes")

    replace = engine.conversations.replace

    async def lose_redis_after_commit(session, previous, updated):
        if previous.in_flight and not updated.in_flight:
            raise ConnectionError("simulated Redis outage after PostgreSQL commit")
        return await replace(session, previous, updated)

    with monkeypatch.context() as patch:
        patch.setattr(engine.conversations, "replace", lose_redis_after_commit)
        with pytest.raises(ConnectionError):
            await act("add_credits", 7, amount=30)
    key = f"csol:conversation:{customer}"
    reserved = json.loads(await redis.get(key))
    assert "version" not in reserved and reserved["in_flight"]["tool"] == "add_credits"

    engine = Engine(Conversations(redis, registry, "versioned"), engine.accounts, registry)
    assert await pool.fetchval("SELECT balance FROM csol.customers WHERE customer_id=$1", customer) == 50
    assert (await act("add_credits", 7, amount=40))["outcome"] == "operation_pending"
    result = await act("add_credits", 7, amount=30)
    assert result["receipt"]["balance"] == 50 and result["step"] == CONFIRM[1]
    assert result["receipt"]["operation_id"] == f"{reserved['instance']}.7"
    assert json.loads(await redis.get(key))["version"] == 1
    assert (await act("add_credits", 7, amount=30))["outcome"] == "out_of_step"
    too_early = await engine.invoke(customer, customer, "confirm_package", {"revision": 8, "answer": "yes"}, turn="7")
    assert too_early["outcome"] == "await_fresh_confirmation"
    result = await act("confirm_package", 9, answer="yes")
    assert result["step"] == MENU[1] and result["receipt"]["balance"] == 0
    assert await pool.fetchval("SELECT name FROM csol.customers WHERE customer_id=$1", customer) == "Ari"
    assert await pool.fetchval("SELECT balance FROM csol.customers WHERE customer_id=$1", customer) == 0
    receipts = await pool.fetchval(
        "SELECT count(*) FROM csol.operations WHERE customer_id=$1 AND result ? 'receipt'", customer)
    assert receipts == 2
    assert (await engine.conversations.read(customer, customer)).step == MENU[1]


async def test_competing_purchases_share_one_wallet(live):
    engine, customer, pool = live
    await pool.execute("UPDATE csol.customers SET balance=50 WHERE customer_id=$1", customer)

    async def purchase(session):
        for revision, (tool, args) in enumerate([
            ("record_name", {"name": "Same"}), ("select_service", {"service": "buy_package"}),
            ("match_package", {"benefit": customer}), ("confirm_package", {"answer": "yes"}),
        ]):
            result = await engine.invoke(session, customer, tool, {"revision": revision, **args}, turn=str(revision))
        return result["outcome"]

    results = await asyncio.gather(purchase(customer), purchase(customer + "-other"))
    assert sorted(results) == ["insufficient_funds", "purchased"]
    assert await pool.fetchval("SELECT balance FROM csol.customers WHERE customer_id=$1", customer) == 0


async def test_duplicate_top_up_and_changed_quote(live):
    engine, customer, pool = live

    async def act(tool, revision, **args):
        return await engine.invoke(customer, customer, tool, {"revision": revision, **args}, turn=str(revision))

    await act("record_name", 0, name="Ari")
    assert (await act("select_service", 1, service="buy_credits"))["step"] == CREDITS[1]
    results = await asyncio.gather(act("add_credits", 2, amount=30), act("add_credits", 2, amount=30))
    assert [r["outcome"] for r in results].count("credited") == 1
    assert (await engine.conversations.read(customer, customer)).step == MENU[1]
    await act("select_service", 3, service="buy_package")
    await act("match_package", 4, benefit=customer)
    await pool.execute("UPDATE csol.packages SET price=51 WHERE package_id=$1", customer)
    assert (await act("confirm_package", 5, answer="yes"))["outcome"] == "offer_changed"
    assert await pool.fetchval("SELECT balance FROM csol.customers WHERE customer_id=$1", customer) == 50
