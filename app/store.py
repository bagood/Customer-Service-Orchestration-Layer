import json
from typing import Annotated

from pydantic import Field, StringConstraints
from redis.exceptions import WatchError

from app.model import Conversation, Input

FORMAT_VERSION = 1

Nonempty = Annotated[str, StringConstraints(min_length=1)]
Revision = Annotated[int, Field(ge=0)]


class BindingMismatch(Exception):
    pass


class InvalidConversation(ValueError):
    pass


class ReturnQuestion(Input):
    state: Nonempty
    step: Nonempty
    revision: Revision
    turn: Nonempty


class Reservation(Input):
    tool: Nonempty
    arguments: dict[str, object]
    turn: Nonempty


class Envelope(Input):
    version: int
    customer: Nonempty
    state: Nonempty
    step: Nonempty
    instance: Nonempty
    revision: Revision
    return_question: ReturnQuestion | None = None
    in_flight: Reservation | None = None
    context: dict[str, dict[str, object]]


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate record key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


class ConversationCodec:
    def __init__(self, registry):
        self.registry = registry

    def decode(self, raw):
        try:
            data = json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
            record = Envelope.model_validate(data)
            if record.version != FORMAT_VERSION:
                raise ValueError("unsupported conversation version")
            conversation = Conversation(
                **record.model_dump(exclude={"version", "context"}), _stored=raw, _context=record.context,
            )
            position = conversation.position
            registered = self.registry.steps.get(position)
            if registered is None:
                raise ValueError(f"unknown active step {position!r}")
            if record.return_question and (
                record.return_question.state, record.return_question.step, record.return_question.revision
            ) != (*position, conversation.revision):
                raise ValueError("return question does not match the active step and revision")
            if record.in_flight:
                name = record.in_flight.tool
                if name == registered.definition.action.__name__:
                    schema = registered.definition.schema
                elif name in self.registry.global_actions:
                    _, schema = self.registry.global_actions[name]
                else:
                    raise ValueError("in-flight tool is unavailable at the active step")
                args = schema.model_validate(record.in_flight.arguments)
                if args.revision != conversation.revision or args.model_dump(mode="json") != record.in_flight.arguments:
                    raise ValueError("in-flight arguments do not match the active revision and schema")

            for workflow_id, values in record.context.items():
                if workflow_id not in self.registry.workflows:
                    raise ValueError(f"unknown workflow context {workflow_id!r}")
                rules = self.registry.workflows[workflow_id].context
                for key, value in values.items():
                    if key not in rules:
                        raise ValueError(f"unknown context field {workflow_id}.{key}")
                    rules[key].validate(value, f"{workflow_id}.{key}")
            return conversation
        except (ValueError, RecursionError) as exc:
            raise InvalidConversation(str(exc)) from exc

    def encode(self, conversation):
        data = {"version": FORMAT_VERSION, "context": conversation._context}
        data.update({key: getattr(conversation, key) for key in Envelope.model_fields if key not in data})
        return json.dumps(data, allow_nan=False)


class Conversations:
    def __init__(self, redis, registry):
        self.redis = redis
        self.registry = registry
        self.codec = ConversationCodec(registry)

    async def read(self, session, customer):
        key = f"csol:conversation:{session}"
        raw = await self.redis.get(key)
        if raw is None:
            initial = Conversation(customer, *self.registry.start)
            await self.redis.set(key, self.codec.encode(initial), nx=True)
            raw = await self.redis.get(key)
        if raw is None:
            raise InvalidConversation("conversation disappeared during creation")
        conversation = self.codec.decode(raw)
        if conversation.customer != customer:
            raise BindingMismatch
        return conversation

    async def replace(self, session, previous, updated):
        """Compare the original Redis value, including any in-flight reservation."""
        key = f"csol:conversation:{session}"
        async with self.redis.pipeline() as pipe:
            try:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if raw is None or raw != previous._stored:
                    return False
                encoded = self.codec.encode(updated)
                pipe.multi()
                pipe.set(key, encoded)
                await pipe.execute()
                updated._stored = encoded.encode("utf-8") if isinstance(raw, bytes) else encoded
                return True
            except WatchError:
                return False
