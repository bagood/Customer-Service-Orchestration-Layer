from pathlib import Path

from app.model import Action, Answer, MENU

RETURN_INSTRUCTION = (Path(__file__).parent / "instructions/return_to_landing.md").read_text().strip()


async def request_return_to_landing(conversation, args, db, turn):
    """Ask for confirmation before leaving the current procedure."""
    conversation.return_question = {
        "state": conversation.state, "step": conversation.step, "revision": conversation.revision + 1, "turn": turn,
    }
    return {"outcome": "return_requested"}


async def resolve_return_to_landing(conversation, args, db, turn):
    """Apply the answer to the pending return-to-menu question."""
    if args.answer == "unclear":
        conversation.return_question.update(revision=conversation.revision + 1, turn=turn)
        return {"outcome": "clarify_return"}
    conversation.return_question = None
    if args.answer == "yes":
        conversation.clear_offer()
        conversation.move(MENU)
        return {"outcome": "returned_to_menu"}
    return {"outcome": "resumed"}


actions = {request_return_to_landing: Action, resolve_return_to_landing: Answer}
