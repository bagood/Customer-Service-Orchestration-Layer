from app.model import Action, MENU, Step, Text, wording


class Name(Action):
    name: Text


def identification_instruction(conversation):
    return wording(__file__)


async def record_name(conversation, args, db, turn):
    """Record the supplied display name on the bound customer account."""
    result = await db.post(conversation, "record_name", name=args.name)
    if result["outcome"] == "name_recorded":
        conversation.display_name = args.name
        conversation.move(MENU)
    return result


step = Step(identification_instruction, record_name, Name)
