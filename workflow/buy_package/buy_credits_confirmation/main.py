from app.model import Answer, CREDITS, MENU, Step, wording


def detour_instruction(conversation):
    return wording(__file__)


async def confirm_credit_detour(conversation, args, db, turn):
    """Apply the customer's answer to the offer of a credit top-up."""
    if args.answer == "unclear":
        return {"outcome": "clarify_top_up"}
    if args.answer == "yes":
        conversation.move(CREDITS)
        return {"outcome": "top_up_selected"}
    conversation.clear_offer()
    conversation.move(MENU)
    return {"outcome": "top_up_declined"}


step = Step(detour_instruction, confirm_credit_detour, Answer)
