import json
from typing import Annotated

from pydantic import Field, StringConstraints
from redis.exceptions import WatchError

from app.model import Conversation, Input

FORMAT_VERSION = 1
LEGACY_STEPS = frozenset({
    ("start", "identification"),
    ("landing", "intent_classification"),
    ("buy_package", "package_preference_identification"),
    ("buy_package", "user_confirmation"),
    ("buy_package", "buy_credits_confirmation"),
    ("buy_credits", "amount_of_balance"),
})
LEGACY_CONTEXT = {
    "display_name": ("start", "display_name"),
    "offer": ("buy_package", "offer"),
    "offer_presented_turn": ("buy_package", "offer_presented_turn"),
    "shortfall": ("buy_package", "shortfall"),
}

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
    customer: Nonempty
    state: Nonempty
    step: Nonempty
    instance: Nonempty
    revision: Revision
    return_question: ReturnQuestion | None = None
    in_flight: Reservation | None = None


class LegacyOffer(Input):
    package_id: str
    name: str
    benefits: str
    quota_gb: Annotated[int, Field(ge=0)]
    price: Annotated[int, Field(ge=1)]


class LegacyRecord(Envelope):
    display_name: str | None = None
    offer: LegacyOffer | None = None
    offer_presented_turn: str | None = None
    shortfall: int | None = None


class VersionedRecord(Envelope):
    version: int
    context: dict[str, dict[str, object]]


def check_legacy_layout(registry):
    for state, step in sorted(registry.steps.keys() - LEGACY_STEPS):
        raise ValueError(f"workflow/{state}/workflow.yaml: step {step!r} requires versioned writes")
    if missing := sorted(LEGACY_STEPS - registry.steps.keys()):
        state, step = missing[0]
        raise ValueError(f"workflow/{state}/workflow.yaml: legacy writes require step {step!r}")
    for workflow_id, field in LEGACY_CONTEXT.values():
        if field not in registry.workflows[workflow_id].context:
            raise ValueError(f"workflow/{workflow_id}/workflow.yaml: legacy writes require context.{field}")
    legacy_types = {"display_name": "string", "offer": "object", "offer_presented_turn": "string", "shortfall": "integer"}
    for workflow_id, workflow in registry.workflows.items():
        for key, rule in workflow.context.items():
            if LEGACY_CONTEXT.get(key) != (workflow_id, key) or rule.type != legacy_types[key] or not rule.nullable:
                raise ValueError(f"workflow/{workflow_id}/workflow.yaml: context.{key} requires versioned writes")
            if key == "offer":
                fields = {"package_id": "string", "name": "string", "benefits": "string",
                          "quota_gb": "integer", "price": "integer"}
                if fields != {name: value.type for name, value in rule.fields.items()} or any(
                    field.nullable for field in rule.fields.values()
                ):
                    raise ValueError(f"workflow/{workflow_id}/workflow.yaml: context.offer requires versioned writes")
                for name, minimum in (("quota_gb", 0), ("price", 1)):
                    bound = rule.fields[name].minimum
                    if bound is None or bound < minimum:
                        raise ValueError(
                            f"workflow/{workflow_id}/workflow.yaml: context.offer.fields.{name} requires versioned writes"
                        )


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
    def __init__(self, registry, write_format):
        if write_format not in ("legacy", "versioned"):
            raise ValueError("CSOL_CONVERSATION_WRITE_FORMAT must be legacy or versioned")
        if write_format == "legacy":
            check_legacy_layout(registry)
        self.registry = registry
        self.write_format = write_format

    def decode(self, raw):
        try:
            data = json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant)
            if not isinstance(data, dict):
                raise ValueError("record must be an object")
            if "version" in data:
                if type(data["version"]) is not int or data["version"] != FORMAT_VERSION:
                    raise ValueError("unsupported conversation version")
                record = VersionedRecord.model_validate(data)
                context = record.context
            else:
                record = LegacyRecord.model_validate(data)
                if (record.state, record.step) not in LEGACY_STEPS:
                    raise ValueError("unknown legacy step")
                context = {}
                for key, (workflow_id, field) in LEGACY_CONTEXT.items():
                    if key in data:
                        context.setdefault(workflow_id, {})[field] = getattr(record, key)
                if record.offer is not None:
                    context["buy_package"]["offer"] = record.offer.model_dump()

            conversation = Conversation(**record.model_dump(include=set(Envelope.model_fields)), _stored=raw)
            position = conversation.position
            if position not in self.registry.steps:
                raise ValueError(f"unknown active step {position!r}")
            if record.return_question and (
                record.return_question.state, record.return_question.step, record.return_question.revision
            ) != (*position, conversation.revision):
                raise ValueError("return question does not match the active step and revision")
            if record.in_flight:
                registered = self.registry.steps[position].definition
                name = record.in_flight.tool
                if name == registered.action.__name__:
                    schema = registered.schema
                elif name in self.registry.global_actions:
                    _, schema = self.registry.global_actions[name]
                else:
                    raise ValueError("in-flight tool is unavailable at the active step")
                args = schema.model_validate(record.in_flight.arguments)
                if args.revision != conversation.revision or args.model_dump(mode="json") != record.in_flight.arguments:
                    raise ValueError("in-flight arguments do not match the active revision and schema")

            for workflow_id, values in context.items():
                if workflow_id not in self.registry.workflows:
                    raise ValueError(f"unknown workflow context {workflow_id!r}")
                rules = self.registry.workflows[workflow_id].context
                for key, value in values.items():
                    if key not in rules:
                        raise ValueError(f"unknown context field {workflow_id}.{key}")
                    rules[key].validate(value, f"{workflow_id}.{key}")
            conversation._context = context
            return conversation
        except (ValueError, RecursionError) as exc:
            raise InvalidConversation(str(exc)) from exc

    def encode(self, conversation):
        data = {key: getattr(conversation, key) for key in Envelope.model_fields}
        if self.write_format == "versioned":
            data.update(version=FORMAT_VERSION, context=conversation._context)
        else:
            if conversation.position not in LEGACY_STEPS:
                raise InvalidConversation("active step requires versioned writes")
            fields = set(LEGACY_CONTEXT.values())
            for workflow_id, values in conversation._context.items():
                if any((workflow_id, key) not in fields for key in values):
                    raise InvalidConversation("workflow context requires versioned writes")
            for key, (workflow_id, field) in LEGACY_CONTEXT.items():
                rule = self.registry.workflows[workflow_id].context[field]
                namespace = conversation._context.get(workflow_id, {})
                if field in namespace:
                    data[key] = rule.validate(namespace[field], f"{workflow_id}.{field}")
                else:
                    data[key] = rule.default(field) if rule.default_json is not None else None
            LegacyRecord.model_validate(data)
        return json.dumps(data, allow_nan=False)


class Conversations:
    def __init__(self, redis, registry, write_format="legacy"):
        self.redis = redis
        self.registry = registry
        self.codec = ConversationCodec(registry, write_format)

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
