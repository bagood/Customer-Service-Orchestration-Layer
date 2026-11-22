from app.model import Action, Step, Text
from workflow.start.helper import update_name


class Name(Action):
    name: Text


def identification_instruction(workflow):
    return workflow.instruction_text


async def record_name(conversation, args, db, turn, workflow):
    """Record the supplied display name on the bound customer account."""
    result = await update_name(db, conversation, args.name)
    if result["outcome"] == "name_recorded":
        workflow.context()["display_name"] = args.name
        workflow.move("menu")
    return result


step = Step(identification_instruction, record_name, Name)
