from app.model import Answer, DETOUR, MENU, PREFERENCES, Step, wording


def purchase_instruction(conversation):
    return wording(__file__)


async def confirm_package(conversation, args, db, turn):
    """Apply the customer's answer to the current package offer."""
    if args.answer == "unclear":
        return {"outcome": "clarify_purchase"}
    if args.answer == "no":
        conversation.clear_offer()
        conversation.move(PREFERENCES)
        return {"outcome": "offer_declined"}

    if conversation.offer_presented_turn == turn:
        return {"outcome": "await_fresh_confirmation"}

    result = await db.post(conversation, "purchase")
    if result["outcome"] == "insufficient_funds":
        conversation.shortfall = result["shortfall"]
        conversation.move(DETOUR)
    elif result["outcome"] == "offer_changed":
        conversation.clear_offer()
        conversation.move(PREFERENCES)
    elif result["outcome"] == "purchased":
        conversation.clear_offer()
        conversation.move(MENU)
    return result


step = Step(purchase_instruction, confirm_package, Answer)
