from app.model import Answer, Step
from workflow.buy_package import clear_offer
from workflow.buy_package.helper import purchase


def purchase_instruction(workflow):
    return workflow.instruction_text


async def confirm_package(conversation, args, db, turn, workflow):
    """Apply the customer's answer to the current package offer."""
    if args.answer == "unclear":
        return {"outcome": "clarify_purchase"}
    if args.answer == "no":
        clear_offer(workflow)
        workflow.move("preferences")
        return {"outcome": "offer_declined"}

    context = workflow.context()
    if context["offer_presented_turn"] == turn:
        return {"outcome": "await_fresh_confirmation"}

    result = await purchase(db, conversation, context["offer"])
    if result["outcome"] == "insufficient_funds":
        context["shortfall"] = result["shortfall"]
        workflow.move("credit_detour")
    elif result["outcome"] == "offer_changed":
        clear_offer(workflow)
        workflow.move("preferences")
    elif result["outcome"] == "purchased":
        clear_offer(workflow)
        workflow.move("menu")
    return result


step = Step(purchase_instruction, confirm_package, Answer)
