from typing import Literal

from app.model import Action, CREDITS, PREFERENCES, Step, wording


class Selection(Action):
    service: Literal["buy_package", "buy_credits", "unclear"]


def menu_instruction(conversation):
    return wording(__file__)


async def select_service(conversation, args, db, turn):
    """Select the service requested in the customer's message."""
    if args.service == "unclear":
        return {"outcome": "clarify_service"}
    conversation.move(PREFERENCES if args.service == "buy_package" else CREDITS)
    return {"outcome": "service_selected"}


step = Step(menu_instruction, select_service, Selection)
