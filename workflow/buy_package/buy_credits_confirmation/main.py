from app.model import Answer, Step
from workflow.buy_package import clear_offer


def detour_instruction(workflow):
    return workflow.instruction_text


async def confirm_credit_detour(conversation, args, db, turn, workflow):
    """Apply the customer's answer to the offer of a credit top-up."""
    if args.answer == "unclear":
        return {"outcome": "clarify_top_up"}
    if args.answer == "yes":
        workflow.move("top_up")
        return {"outcome": "top_up_selected"}
    clear_offer(workflow)
    workflow.move("menu")
    return {"outcome": "top_up_declined"}


step = Step(detour_instruction, confirm_credit_detour, Answer)
