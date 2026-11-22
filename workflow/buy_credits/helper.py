async def change_balance(conn, account, delta):
    return await conn.fetchval(
        "UPDATE csol.customers SET balance=balance+$2 WHERE customer_id=$1 RETURNING balance", account, delta,
    )


async def top_up(accounts, conversation, amount):
    async def apply(conn, balance):
        if balance + amount > 2**63 - 1:
            return {"outcome": "balance_limit"}
        posted = await change_balance(conn, conversation.customer, amount)
        return {
            "outcome": "credited",
            "receipt": {"change": amount, "balance": posted, "operation_id": conversation.operation_id},
        }

    return await accounts.post(conversation, "top_up", apply)
