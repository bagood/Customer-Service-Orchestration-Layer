import hashlib
import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import MappingProxyType

from mcp.shared.tool_name_validation import validate_tool_name

from app.manifest import ContextRule, identifier, read_manifest
from app.model import Action, Conversation, Input, Position, Step

WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / "workflow"
HERMES_UNSUPPORTED = re.compile(r"[^A-Za-z0-9_]")


def hermes_name(name):
    # Match the pinned Hermes MCP adapter's provider-facing name.
    full = "mcp__csol__" + HERMES_UNSUPPORTED.sub("_", name)
    if len(full) <= 64:
        return full
    return f"{full[:55]}_{hashlib.sha256(full.encode()).hexdigest()[:8]}"


@dataclass(frozen=True)
class Workflow:
    context: Mapping[str, ContextRule]
    destinations: Mapping[str, Position]
    dependencies: Mapping[str, tuple[str, ...]]
    reset_fields: tuple[str, ...]
    export_context: Callable | None


@dataclass(frozen=True)
class RegisteredStep:
    definition: Step
    instruction_text: str

    @property
    def names(self):
        return self.definition.names


@dataclass(frozen=True)
class Tool:
    name: str
    description: str | None
    schema: type[Input]


@dataclass(frozen=True)
class Registry:
    workflows: Mapping[str, Workflow]
    steps: Mapping[Position, RegisteredStep]
    global_actions: Mapping[str, tuple[Callable, type[Action]]]
    catalog: tuple[Tool, ...]
    start: Position
    menu: Position
    return_instruction: str

    def allowed(self, conversation):
        return [*self.steps[conversation.position].names, *self.global_actions]

    def reset_context(self, conversation):
        for workflow_id, workflow in self.workflows.items():
            namespace = conversation._context.get(workflow_id, {})
            for key in workflow.reset_fields:
                namespace.pop(key, None)

    def instruction_context(self, conversation):
        result = {}
        for workflow_id, workflow in self.workflows.items():
            if workflow.export_context:
                exported = workflow.export_context(WorkflowAccess(self, conversation, workflow_id))
                overlap = result.keys() & exported.keys()
                if overlap or "recorded_arguments" in exported:
                    raise ValueError(f"{workflow_id}: conflicting instruction context keys")
                result.update(exported)
        return result


class WorkflowContext:
    def __init__(self, conversation, workflow_id, rules, allowed):
        self._conversation = conversation
        self._workflow_id = workflow_id
        self._rules = rules
        self._allowed = allowed

    def _rule(self, key):
        if key not in self._allowed:
            raise KeyError(f"Undeclared context access: {self._workflow_id}.{key}")
        return self._rules[key]

    def __getitem__(self, key):
        rule = self._rule(key)
        namespace = self._conversation._context.get(self._workflow_id, {})
        if key in namespace:
            return rule.validate(namespace[key], f"{self._workflow_id}.{key}")
        return rule.default(key)

    def __setitem__(self, key, value):
        rule = self._rule(key)
        validated = rule.validate(value, f"{self._workflow_id}.{key}")
        self._conversation._context.setdefault(self._workflow_id, {})[key] = validated

    def reset(self, *keys):
        for key in keys:
            self._rule(key)
        namespace = self._conversation._context.get(self._workflow_id, {})
        for key in keys:
            namespace.pop(key, None)


class WorkflowAccess:
    def __init__(self, registry, conversation: Conversation, workflow_id, instruction_text=None):
        self._registry = registry
        self._conversation = conversation
        self._workflow_id = workflow_id
        self.instruction_text = instruction_text

    def context(self, workflow_id=None):
        current = self._registry.workflows[self._workflow_id]
        if workflow_id is None or workflow_id == self._workflow_id:
            return WorkflowContext(self._conversation, self._workflow_id, current.context, current.context)
        allowed = current.dependencies.get(workflow_id)
        if allowed is None:
            raise KeyError(f"Undeclared context dependency: {self._workflow_id} -> {workflow_id}")
        return WorkflowContext(self._conversation, workflow_id, self._registry.workflows[workflow_id].context, allowed)

    def move(self, alias):
        self._conversation.move(self._registry.workflows[self._workflow_id].destinations[alias])


def _within(path, root):
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"{path}: path escapes the workflow root")
    return path


def _text(path):
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path}: instruction file must contain text")
    return text


def _load_step(root, path, workflow_id, directory):
    module_name = f"workflow.{workflow_id}.{directory}.main"
    try:
        source = _within(path.parent / directory / "main.py", root)
        if not source.is_file():
            raise ValueError("missing main.py")
        _within(source.parent / "__init__.py", root)
        instruction = _text(_within(source.with_name("instruction.md"), root))
        module = import_module(module_name)
        if Path(module.__file__).resolve() != source.resolve():
            raise ValueError("module was imported from a different path")
        step = module.step
        if not isinstance(step, Step):
            raise ValueError("step must export a Step")
        if (not inspect.isfunction(step.instruction) or inspect.iscoroutinefunction(step.instruction)
                or inspect.isgeneratorfunction(step.instruction)):
            raise ValueError("instruction must be a synchronous function")
        if not inspect.iscoroutinefunction(step.action):
            raise ValueError("action must be an async function")
        inspect.signature(step.instruction).bind(None)
        inspect.signature(step.action).bind(None, None, None, None, None)
        if not isinstance(step.schema, type) or not issubclass(step.schema, Action):
            raise ValueError("tool schema must inherit Action")
        return RegisteredStep(step, instruction)
    except Exception as exc:
        raise ValueError(f"{path}: {module_name}: {exc}") from exc


def build_registry(root=WORKFLOW_ROOT):
    root = root.resolve()
    manifests = {}
    paths = {}
    for directory in sorted(root.iterdir()):
        path = directory / "workflow.yaml"
        if not directory.is_dir():
            continue
        if not path.is_file():
            undeclared = sorted(str(source.relative_to(root)) for source in directory.glob("*/main.py"))
            if undeclared:
                raise ValueError(f"{path}: missing manifest for {', '.join(undeclared)}")
            continue
        _within(path, root)
        try:
            identifier(directory.name)
        except ValueError as exc:
            raise ValueError(f"{path}: workflow directory {directory.name!r}: {exc}") from exc
        paths[directory.name] = path
        manifests[directory.name] = read_manifest(path)

    aliases = {}
    entries = {"start_at": [], "return_to_menu_at": []}
    for workflow_id, manifest in manifests.items():
        path = paths[workflow_id]
        if not manifest.steps:
            raise ValueError(f"{path}: steps must declare at least one step")
        directories = set()
        for alias, declaration in manifest.steps.items():
            directory = declaration.directory
            if directory in directories:
                raise ValueError(f"{path}: steps.{alias}.directory repeats {directory!r}")
            directories.add(directory)
            aliases[workflow_id, alias] = (workflow_id, directory)
        undeclared = sorted(source.parent.name for source in path.parent.glob("*/main.py")
                            if source.parent.name not in directories)
        if undeclared:
            raise ValueError(f"{path}: steps missing declarations for {', '.join(undeclared)}")
        for key, positions in entries.items():
            alias = getattr(manifest, key)
            if alias is not None:
                if (workflow_id, alias) not in aliases:
                    raise ValueError(f"{path}: {key} references unknown step {alias!r}")
                positions.append((path, aliases[workflow_id, alias]))
    for key, positions in entries.items():
        if len(positions) != 1:
            locations = ", ".join(str(path) for path, _ in positions) or str(root / "*/workflow.yaml")
            raise ValueError(f"{locations}: expected exactly one {key}, found {len(positions)}")

    workflows = {}
    steps = {}
    for workflow_id, manifest in manifests.items():
        path = paths[workflow_id]
        destinations = {}
        for alias, target in manifest.destinations.items():
            pair = target.workflow, target.step
            if pair not in aliases:
                raise ValueError(f"{path}: destinations.{alias} references unknown step {pair!r}")
            destinations[alias] = aliases[pair]
        for dependency, fields in manifest.context_dependencies.items():
            if dependency == workflow_id or dependency not in manifests:
                raise ValueError(f"{path}: context_dependencies.{dependency} must reference another workflow")
            for field in fields:
                if field not in manifests[dependency].context:
                    raise ValueError(f"{path}: context_dependencies.{dependency} references unknown field {field!r}")
        for field in manifest.reset_on_return_to_menu:
            if field not in manifest.context:
                raise ValueError(f"{path}: reset_on_return_to_menu references unknown field {field!r}")

        _within(path.parent / "__init__.py", root)
        try:
            export = getattr(import_module(f"workflow.{workflow_id}"), "export_context", None)
            if export is not None:
                if not callable(export) or inspect.iscoroutinefunction(export):
                    raise ValueError("export_context must be a synchronous function")
                inspect.signature(export).bind(None)
        except Exception as exc:
            raise ValueError(f"{path}: workflow.{workflow_id}: {exc}") from exc
        workflows[workflow_id] = Workflow(
            MappingProxyType({key: field.compile() for key, field in manifest.context.items()}),
            MappingProxyType(destinations),
            MappingProxyType({key: tuple(fields) for key, fields in manifest.context_dependencies.items()}),
            tuple(manifest.reset_on_return_to_menu),
            export,
        )
        for declaration in manifest.steps.values():
            directory = declaration.directory
            steps[workflow_id, directory] = _load_step(root, path, workflow_id, directory)

    start, menu = entries["start_at"][0][1], entries["return_to_menu_at"][0][1]
    # Visit reachable workflows in route order, then any standalone workflows.
    pending = [*reversed(workflows), menu[0], start[0]]
    ordered = {}
    while pending:
        workflow_id = pending.pop()
        if workflow_id not in ordered:
            workflow = ordered[workflow_id] = workflows[workflow_id]
            pending.extend(target[0] for target in reversed(tuple(workflow.destinations.values())))
    steps = {
        (workflow_id, declaration.directory): steps[workflow_id, declaration.directory]
        for workflow_id in ordered
        for declaration in manifests[workflow_id].steps.values()
    }

    global_module = import_module("global.main")
    globals_by_name = {}
    catalog = []
    names = {}
    model_names = {}

    def register(tool, source):
        validation = validate_tool_name(tool.name)
        if not validation.is_valid:
            raise ValueError(f"{source}: incompatible MCP tool name {tool.name!r}. {' '.join(validation.warnings)}")
        model_name = hermes_name(tool.name)
        if tool.name in names or model_name in model_names:
            previous = names.get(tool.name) or model_names[model_name]
            raise ValueError(f"{source}: duplicate MCP tool {tool.name!r} ({model_name}) with {previous}")
        try:
            schema = tool.schema.model_json_schema()
            if any(
                field.validation_alias not in (None, name) or field.serialization_alias not in (None, name)
                for name, field in tool.schema.model_fields.items()
            ):
                raise ValueError("tool fields must use the same names in input and stored arguments")
            properties = schema["properties"]
            if schema.get("type") != "object" or "binding" in properties:
                raise ValueError("tool schema must be an object and cannot declare binding")
            if tool.schema is not Input and (
                tool.schema.model_fields["revision"].annotation is not int
                or "revision" not in schema.get("required", ())
                or properties["revision"].get("type") != "integer"
            ):
                raise ValueError("action schema must require an integer revision")
        except Exception as exc:
            raise ValueError(f"{source}: invalid schema for {tool.name}: {exc}") from exc
        names[tool.name] = model_names[model_name] = source
        catalog.append(tool)

    for (workflow_id, directory), registered in steps.items():
        instruction, action = registered.names
        source = f"{paths[workflow_id]}: workflow.{workflow_id}.{directory}.main"
        register(Tool(instruction, "Read the current question, context, revision and appropriate action.", Input), source)
        definition = registered.definition
        register(Tool(action, definition.action.__doc__, definition.schema), source)
    for handler, schema in global_module.actions.items():
        name = handler.__name__
        register(Tool(name, handler.__doc__, schema), "global.main")
        globals_by_name[name] = handler, schema

    return Registry(
        MappingProxyType(ordered), MappingProxyType(steps), MappingProxyType(globals_by_name),
        tuple(catalog), start, menu,
        global_module.RETURN_INSTRUCTION,
    )
