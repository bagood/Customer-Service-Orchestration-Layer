from typing import Annotated

from pydantic import Field
from app.model import Action, Step, Text
from workflow.buy_package.helper import match_preferences


class Preferences(Action):
    benefit: Text | None = None
    min_quota_gb: Annotated[int, Field(ge=0, le=2**31 - 1)] | None = None
    max_price: Annotated[int, Field(ge=0, le=2**63 - 1)] | None = None


def preference_instruction(workflow):
    return workflow.instruction_text


async def match_package(conversation, args, db, turn, workflow):
    """Find the lowest priced package meeting the supplied preferences."""
    if all(value is None for value in (args.benefit, args.min_quota_gb, args.max_price)):
        return {"outcome": "clarify_preferences"}
    offer = await match_preferences(db, args.benefit, args.min_quota_gb, args.max_price)
    if offer is None:
        return {"outcome": "no_match"}
    context = workflow.context()
    context["offer"] = offer
    context["offer_presented_turn"] = turn
    workflow.move("confirm")
    return {"outcome": "offer_selected"}


step = Step(preference_instruction, match_package, Preferences)
