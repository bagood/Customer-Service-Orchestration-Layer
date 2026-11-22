from app.model import Action, CONFIRM, CreditAmount, MENU, Step, wording


class TopUp(Action):
    amount: CreditAmount


def credit_instruction(conversation):
    return wording(__file__)


async def add_credits(conversation, args, db, turn):
    """Post the customer's requested positive whole-credit amount."""
    result = await db.post(conversation, "top_up", amount=args.amount)
    if result["outcome"] == "credited":
        conversation.shortfall = None
        if conversation.offer:
            conversation.offer_presented_turn = turn
        conversation.move(CONFIRM if conversation.offer else MENU)
    return result


step = Step(credit_instruction, add_credits, TopUp)
