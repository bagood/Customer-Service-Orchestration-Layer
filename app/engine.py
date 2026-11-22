from copy import deepcopy
from importlib import import_module

from pydantic import ValidationError
from app.model import START, MENU, PREFERENCES, CONFIRM, DETOUR, CREDITS, Input
from workflow.start.identification.main import step as identification
from workflow.landing.intent_classification.main import step as menu
from workflow.buy_package.package_preference_identification.main import step as preferences
from workflow.buy_package.user_confirmation.main import step as purchase
from workflow.buy_package.buy_credits_confirmation.main import step as detour
from workflow.buy_credits.amount_of_balance.main import step as credits

landing = import_module("global.main")
STEPS = {
    START: identification,
    MENU: menu,
    PREFERENCES: preferences,
    CONFIRM: purchase,
    DETOUR: detour,
    CREDITS: credits,
}
GLOBAL = {handler.__name__: (handler, schema) for handler, schema in landing.actions.items()}


def current_step(c):
    return STEPS[c.state, c.step]


def allowed(c):
    return [*current_step(c).names, *GLOBAL]


def response(c, outcome, **facts):
    step = current_step(c)
    question, action = step.instruction(c), step.action.__name__
    context = {"display_name": c.display_name}
    if c.offer:
        context["offer"] = c.offer
    if c.shortfall is not None:
        context["shortfall"] = c.shortfall
    if c.return_question:
        question, action = landing.RETURN_INSTRUCTION, "resolve_return_to_landing"
    if c.in_flight:
        question = "The previous action is pending. Repeat its recorded arguments to reconcile its outcome."
        action = c.in_flight["tool"]
        context["recorded_arguments"] = c.in_flight["arguments"]
    return {
        "state": c.state, "step": c.step, "revision": c.revision, "outcome": outcome,
        "allowed_tools": allowed(c),
        "instruction": {"question": question, "context": context, "action": action}, **facts,
    }


class Engine:
    def __init__(self, conversations, accounts):
        self.conversations = conversations
        self.accounts = accounts

    async def invoke(self, session, customer, name, arguments, *, turn):
        c = await self.conversations.read(session, customer)
        step = current_step(c)
        if name not in allowed(c):
            return response(c, "out_of_step")
        if name == step.instruction.__name__:
            return response(c, "invalid_input" if arguments else "instruction")
        handler, schema = GLOBAL.get(name, (step.action, step.schema))
        try:
            args = schema.model_validate(arguments)
        except ValidationError as exc:
            return response(c, "invalid_input", issues=[
                {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                for e in exc.errors(include_input=False)
            ])
        if args.revision != c.revision:
            return response(c, "stale_revision")
        if c.return_question and name != "resolve_return_to_landing":
            return response(c, "return_pending")
        if name == "resolve_return_to_landing":
            question = c.return_question
            if not question or (question["state"], question["step"], question["revision"]) != (c.state, c.step, c.revision):
                return response(c, "no_pending_return")
            if question.get("turn") == turn:
                return response(c, "await_fresh_confirmation")

        command = {"tool": name, "arguments": args.model_dump()}
        if c.in_flight and (c.in_flight["tool"] != name or c.in_flight["arguments"] != command["arguments"]):
            return response(c, "operation_pending")
        if not c.in_flight:
            reserved = deepcopy(c)
            reserved.in_flight = {**command, "turn": turn}
            if not await self.conversations.replace(session, c, reserved):
                return response(await self.conversations.read(session, customer), "revision_conflict")
            c = reserved

        updated = deepcopy(c)
        result = await handler(updated, args, self.accounts, c.in_flight["turn"])
        updated.in_flight = None
        updated.revision += 1
        if not await self.conversations.replace(session, c, updated):
            return response(await self.conversations.read(session, customer), "revision_conflict")
        return response(updated, **result)


def catalog():
    for step in STEPS.values():
        yield step.names[0], "Read the current question, context, revision and appropriate action.", Input
        yield step.names[1], step.action.__doc__, step.schema
    for name, (handler, schema) in GLOBAL.items():
        yield name, handler.__doc__, schema
