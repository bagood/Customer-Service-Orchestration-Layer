from typing import Literal

from app.model import Action, Step


class Selection(Action):
    service: Literal["buy_package", "buy_credits", "unclear"]


def menu_instruction(workflow):
    return workflow.instruction_text


async def select_service(conversation, args, db, turn, workflow):
    """Select the service requested in the customer's message."""
    if args.service == "unclear":
        return {"outcome": "clarify_service"}
    workflow.move("preferences" if args.service == "buy_package" else "top_up")
    return {"outcome": "service_selected"}


step = Step(menu_instruction, select_service, Selection)
