async def update_name(accounts, conversation, name):
    async def apply(conn, balance):
        await conn.execute("UPDATE csol.customers SET name=$2 WHERE customer_id=$1", conversation.customer, name)
        return {"outcome": "name_recorded"}

    return await accounts.post(conversation, "record_name", apply)
