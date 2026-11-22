import json


CATALOG_FIELDS = "package_id, name, benefits, quota_gb, price"


class Accounts:
    def __init__(self, pool):
        self.pool = pool

    async def match(self, benefit, min_quota, max_price):
        row = await self.pool.fetchrow(
            f"""SELECT {CATALOG_FIELDS} FROM csol.packages
                WHERE ($1::text IS NULL OR strpos(lower(benefits), lower($1)) > 0)
                  AND ($2::integer IS NULL OR quota_gb >= $2)
                  AND ($3::bigint IS NULL OR price <= $3)
                ORDER BY price, package_id LIMIT 1""",
            benefit, min_quota, max_price,
        )
        return dict(row) if row else None

    async def post(self, conversation, kind, *, name=None, amount=None):
        account = conversation.customer
        operation = conversation.operation_id
        async with self.pool.acquire() as conn, conn.transaction():
            # Serialize all conversations spending from the same account.
            balance = await conn.fetchval(
                "SELECT balance FROM csol.customers WHERE customer_id=$1 FOR UPDATE", account
            )
            if balance is None:
                return {"outcome": "account_missing"}
            prior = await conn.fetchval(
                "SELECT result FROM csol.operations WHERE operation_id=$1", operation
            )
            if prior is not None:
                return json.loads(prior)

            if kind == "record_name":
                await conn.execute("UPDATE csol.customers SET name=$2 WHERE customer_id=$1", account, name)
                result = {"outcome": "name_recorded"}
            elif kind == "purchase":
                result = await self._purchase(conn, conversation, balance)
            elif balance + amount > 2**63 - 1:
                result = {"outcome": "balance_limit"}
            else:
                result = await self._change_balance(conn, account, amount, "credited")

            if result["outcome"] in ("purchased", "credited"):
                result["receipt"]["operation_id"] = operation
            await conn.execute(
                """INSERT INTO csol.operations(operation_id, customer_id, kind, result)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                operation, account, kind, json.dumps(result),
            )
            return result

    async def _purchase(self, conn, conversation, balance):
        offer = conversation.offer
        row = await conn.fetchrow(
            f"SELECT {CATALOG_FIELDS} FROM csol.packages WHERE package_id=$1 FOR SHARE",
            offer["package_id"],
        )
        if not row or dict(row) != offer:
            return {"outcome": "offer_changed"}
        if balance < offer["price"]:
            return {"outcome": "insufficient_funds", "balance": balance, "shortfall": offer["price"] - balance}
        result = await self._change_balance(conn, conversation.customer, -offer["price"], "purchased")
        result["receipt"]["package"] = offer
        return result

    @staticmethod
    async def _change_balance(conn, account, delta, outcome):
        balance = await conn.fetchval(
            "UPDATE csol.customers SET balance=balance+$2 WHERE customer_id=$1 RETURNING balance", account, delta,
        )
        return {"outcome": outcome, "receipt": {"change": delta, "balance": balance}}
