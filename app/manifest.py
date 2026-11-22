import json
import keyword
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Mapping

import yaml
from pydantic import AfterValidator, ValidationError, model_validator
from yaml.events import AliasEvent

from app.model import Input


def identifier(value):
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ValueError("expected a Python identifier")
    return value


Identifier = Annotated[str, AfterValidator(identifier)]


class ExplicitLoader(yaml.SafeLoader):
    yaml_implicit_resolvers = {
        initial: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
        for initial, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None) is not None:
            raise yaml.YAMLError(f"YAML anchors and aliases are unsupported at {event.start_mark}")
        if getattr(event, "tag", None) is not None:
            raise yaml.YAMLError(f"explicit YAML tags are unsupported at {event.start_mark}")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_scalar(key_node) if isinstance(key_node, yaml.ScalarNode) else None
            if key is None or key_node.tag != "tag:yaml.org,2002:str":
                raise yaml.YAMLError(f"expected a string key (merge keys are unsupported) at {key_node.start_mark}")
            if key in result:
                raise yaml.YAMLError(f"duplicate key {key!r} at {key_node.start_mark}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


ExplicitLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), "tTfF",
)


@dataclass(frozen=True)
class ContextRule:
    type: str
    nullable: bool
    default_json: str | None
    minimum: int | None
    maximum: int | None
    fields: Mapping[str, "ContextRule"]

    def default(self, key):
        if self.default_json is None:
            raise KeyError(key)
        return json.loads(self.default_json)

    def validate(self, value, key):
        if value is None and self.nullable:
            return None
        expected = {"string": str, "integer": int, "boolean": bool, "object": dict}[self.type]
        if type(value) is not expected:
            raise ValueError(f"{key}: expected {self.type}")
        if self.type == "integer":
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f"{key}: must be at least {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f"{key}: must be at most {self.maximum}")
        if self.type != "object":
            return value

        extra = value.keys() - self.fields.keys()
        if extra:
            raise ValueError(f"{key}: unexpected fields {sorted(map(repr, extra))}")
        result = {}
        for name, rule in self.fields.items():
            path = f"{key}.{name}"
            try:
                result[name] = rule.validate(value[name], path) if name in value else rule.default(path)
            except KeyError:
                raise ValueError(f"{path}: field is required") from None
        return result


class FieldDeclaration(Input):
    type: Literal["string", "integer", "boolean", "object"]
    nullable: bool = False
    default: object = None
    minimum: int | None = None
    maximum: int | None = None
    fields: dict[Identifier, "FieldDeclaration"] | None = None

    @model_validator(mode="after")
    def validate_declaration(self):
        supplied = self.model_fields_set
        if "fields" in supplied or self.type == "object":
            if self.type != "object" or self.fields is None:
                raise ValueError("fields must be declared for object types only")
        for constraint in supplied & {"minimum", "maximum"}:
            if self.type != "integer" or getattr(self, constraint) is None:
                raise ValueError(f"{constraint} requires an integer type and value")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        self.compile()
        return self

    def compile(self):
        fields = MappingProxyType({name: field.compile() for name, field in (self.fields or {}).items()})
        default_json = None
        if "default" in self.model_fields_set:
            rule = ContextRule(self.type, self.nullable, None, self.minimum, self.maximum, fields)
            default_json = json.dumps(rule.validate(self.default, "default"), allow_nan=False)
        return ContextRule(self.type, self.nullable, default_json, self.minimum, self.maximum, fields)


class StepDeclaration(Input):
    directory: Identifier


class Destination(Input):
    workflow: Identifier
    step: Identifier


class Manifest(Input):
    version: Literal[1]
    steps: dict[Identifier, StepDeclaration]
    context: dict[Identifier, FieldDeclaration] = {}
    destinations: dict[Identifier, Destination] = {}
    context_dependencies: dict[Identifier, list[Identifier]] = {}
    reset_on_return_to_menu: list[Identifier] = []
    start_at: Identifier | None = None
    return_to_menu_at: Identifier | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_version(cls, data):
        if isinstance(data, dict) and "version" in data and type(data["version"]) is not int:
            raise ValueError("version must be the integer 1")
        return data

    @model_validator(mode="after")
    def validate_role_aliases(self):
        for role in ("start_at", "return_to_menu_at"):
            if role in self.model_fields_set and getattr(self, role) is None:
                raise ValueError(f"{role} must name a local step alias")
        return self


def read_manifest(path: Path):
    try:
        return Manifest.model_validate(yaml.load(path.read_text(encoding="utf-8"), Loader=ExplicitLoader))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, RecursionError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
