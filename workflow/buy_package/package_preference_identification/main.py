from typing import Annotated

from pydantic import Field
from app.model import Action, CONFIRM, Step, Text, wording


class Preferences(Action):
    benefit: Text | None = None
    min_quota_gb: Annotated[int, Field(ge=0, le=2**31 - 1)] | None = None
    max_price: Annotated[int, Field(ge=0, le=2**63 - 1)] | None = None


def preference_instruction(conversation):
    return wording(__file__)


async def match_package(conversation, args, db, turn):
    """Find the lowest priced package meeting the supplied preferences."""
    if all(value is None for value in (args.benefit, args.min_quota_gb, args.max_price)):
        return {"outcome": "clarify_preferences"}
    offer = await db.match(args.benefit, args.min_quota_gb, args.max_price)
    if offer is None:
        return {"outcome": "no_match"}
    conversation.offer = offer
    conversation.offer_presented_turn = turn
    conversation.move(CONFIRM)
    return {"outcome": "offer_selected"}


step = Step(preference_instruction, match_package, Preferences)
