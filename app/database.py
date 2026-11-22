import json


class Accounts:
    def __init__(self, pool):
        self.pool = pool

    async def post(self, conversation, kind, apply):
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

            result = await apply(conn, balance)
            await conn.execute(
                """INSERT INTO csol.operations(operation_id, customer_id, kind, result)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                operation, account, kind, json.dumps(result),
            )
            return result


async def change_balance(conn, account, delta):
    return await conn.fetchval(
        "UPDATE csol.customers SET balance=balance+$2 WHERE customer_id=$1 RETURNING balance", account, delta,
    )
