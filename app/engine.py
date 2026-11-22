from copy import deepcopy

from pydantic import ValidationError

from app.registry import WorkflowAccess


class Engine:
    def __init__(self, conversations, accounts, registry):
        self.conversations = conversations
        self.accounts = accounts
        self.registry = registry

    def response(self, conversation, outcome, **facts):
        registered = self.registry.steps[conversation.position]
        step = registered.definition
        context = self.registry.instruction_context(conversation)
        if conversation.in_flight:
            question = "The previous action is pending. Repeat its recorded arguments to reconcile its outcome."
            action = conversation.in_flight["tool"]
            context["recorded_arguments"] = conversation.in_flight["arguments"]
        elif conversation.return_question:
            question, action = self.registry.return_instruction, "resolve_return_to_landing"
        else:
            workflow = WorkflowAccess(self.registry, conversation, conversation.state, registered.instruction_text)
            question, action = step.instruction(workflow), step.action.__name__
        return {
            "state": conversation.state, "step": conversation.step, "revision": conversation.revision, "outcome": outcome,
            "allowed_tools": self.registry.allowed(conversation),
            "instruction": {"question": question, "context": context, "action": action}, **facts,
        }

    async def invoke(self, session, customer, name, arguments, *, turn):
        c = await self.conversations.read(session, customer)
        step = self.registry.steps[c.position].definition
        if name not in self.registry.allowed(c):
            return self.response(c, "out_of_step")
        if name == step.instruction.__name__:
            return self.response(c, "invalid_input" if arguments else "instruction")
        global_action = self.registry.global_actions.get(name)
        handler, schema = global_action or (step.action, step.schema)
        try:
            args = schema.model_validate(arguments)
        except ValidationError as exc:
            return self.response(c, "invalid_input", issues=[
                {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                for e in exc.errors(include_input=False)
            ])
        if args.revision != c.revision:
            return self.response(c, "stale_revision")
        if c.return_question and name != "resolve_return_to_landing":
            return self.response(c, "return_pending")
        if name == "resolve_return_to_landing":
            question = c.return_question
            if not question or (question["state"], question["step"], question["revision"]) != (*c.position, c.revision):
                return self.response(c, "no_pending_return")
            if question["turn"] == turn:
                return self.response(c, "await_fresh_confirmation")

        command = {"tool": name, "arguments": args.model_dump(mode="json")}
        if c.in_flight and (c.in_flight["tool"] != name or c.in_flight["arguments"] != command["arguments"]):
            return self.response(c, "operation_pending")
        if not c.in_flight:
            reserved = deepcopy(c)
            reserved.in_flight = {**command, "turn": turn}
            if not await self.conversations.replace(session, c, reserved):
                return self.response(await self.conversations.read(session, customer), "revision_conflict")
            c = reserved

        updated = deepcopy(c)
        access = self.registry if global_action else WorkflowAccess(self.registry, updated, c.state)
        result = await handler(updated, args, self.accounts, c.in_flight["turn"], access)
        updated.in_flight = None
        updated.revision += 1
        if not await self.conversations.replace(session, c, updated):
            return self.response(await self.conversations.read(session, customer), "revision_conflict")
        return self.response(updated, **result)
