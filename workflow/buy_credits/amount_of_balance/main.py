from app.model import Action, CreditAmount, Step
from workflow.buy_credits.helper import top_up


class TopUp(Action):
    amount: CreditAmount


def credit_instruction(workflow):
    return workflow.instruction_text


async def add_credits(conversation, args, db, turn, workflow):
    """Post the customer's requested positive whole-credit amount."""
    result = await top_up(db, conversation, args.amount)
    if result["outcome"] == "credited":
        package = workflow.context("buy_package")
        package["shortfall"] = None
        if package["offer"]:
            package["offer_presented_turn"] = turn
            workflow.move("confirm")
        else:
            workflow.move("menu")
    return result


step = Step(credit_instruction, add_credits, TopUp)
