from workflow.buy_credits.helper import change_balance

CATALOG_FIELDS = "package_id, name, benefits, quota_gb, price"


async def match_preferences(accounts, benefit, min_quota, max_price):
    row = await accounts.pool.fetchrow(
        f"""SELECT {CATALOG_FIELDS} FROM csol.packages
            WHERE ($1::text IS NULL OR strpos(lower(benefits), lower($1)) > 0)
              AND ($2::integer IS NULL OR quota_gb >= $2)
              AND ($3::bigint IS NULL OR price <= $3)
            ORDER BY price, package_id LIMIT 1""",
        benefit, min_quota, max_price,
    )
    return dict(row) if row else None


async def purchase(accounts, conversation, offer):
    async def apply(conn, balance):
        row = await conn.fetchrow(
            f"SELECT {CATALOG_FIELDS} FROM csol.packages WHERE package_id=$1 FOR SHARE",
            offer["package_id"],
        )
        if not row or dict(row) != offer:
            return {"outcome": "offer_changed"}
        price = offer["price"]
        if balance < price:
            return {"outcome": "insufficient_funds", "balance": balance, "shortfall": price - balance}
        posted = await change_balance(conn, conversation.customer, -price)
        return {
            "outcome": "purchased",
            "receipt": {"change": -price, "balance": posted, "operation_id": conversation.operation_id, "package": offer},
        }

    return await accounts.post(conversation, "purchase", apply)
