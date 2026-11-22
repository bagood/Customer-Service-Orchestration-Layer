import shutil
import sys

import pytest

from app.engine import Engine
from app.manifest import read_manifest
from app.registry import WORKFLOW_ROOT, WorkflowAccess, build_registry
from app.store import Conversations
from conftest import STEP_TOOLS

PROBE_MANIFEST = """
version: 1
context:
  counter:
    type: object
    fields:
      count: {type: integer, minimum: 0, default: 0}
      ready: {type: boolean, default: false}
    default: {}
steps:
  count: {directory: record_count}
destinations:
  menu: {workflow: landing, step: menu}
"""
PROBE_STEP = """
from app.model import Action, Step


def count_instruction(workflow):
    return workflow.instruction_text


async def record_count(conversation, args, db, turn, workflow):
    context = workflow.context()
    value = context["counter"]
    value["count"] += 1
    context["counter"] = value
    workflow.move("menu")
    return {"outcome": "counted"}


step = Step(count_instruction, record_count, Action)
"""


@pytest.fixture
def workflow_tree(registry, tmp_path, monkeypatch):
    root = tmp_path / "workflow"
    shutil.copytree(WORKFLOW_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    probe = root / "probe" / "record_count"
    probe.mkdir(parents=True)
    (probe.parent / "workflow.yaml").write_text(PROBE_MANIFEST)
    (probe / "main.py").write_text(PROBE_STEP)
    (probe / "instruction.md").write_text("Count one item.")
    package = sys.modules["workflow"]
    with monkeypatch.context() as patches:
        patches.setattr(package, "__path__", [str(root)])
        for name in list(sys.modules):
            if name.startswith("workflow."):
                patches.delitem(sys.modules, name)
        try:
            yield root
        finally:
            for name in list(sys.modules):
                if name.startswith("workflow."):
                    del sys.modules[name]


def test_catalog_order_and_resolved_destinations(registry):
    global_tools = ("request_return_to_landing", "resolve_return_to_landing")
    assert tuple(tool.name for tool in registry.catalog) == (
        *(name for pair in STEP_TOOLS.values() for name in pair), *global_tools,
    )
    assert registry.workflows["landing"].destinations["top_up"] == ("buy_credits", "amount_of_balance")
    with pytest.raises(TypeError):
        registry.workflows["landing"].destinations["top_up"] = registry.start


@pytest.mark.parametrize(("yaml", "message"), [
    ("version: 1\nversion: 1", "duplicate key"),
    ("version: 1\nsteps: &steps {}\ncontext: *steps", "anchors and aliases"),
    ("version: 1\nsteps: {!!str test: {directory: step}}", "explicit YAML tags"),
    ("version: 1\n<<: {steps: {}}", "merge keys"),
    ("version: 1\n---\nversion: 1", "single document"),
    ("version: 2\nsteps: {}", r"version"),
    ("version: true\nsteps: {}", "version must be the integer 1"),
    ("version: 1\nsteps: {}\nextra: 1", "extra"),
    ("version: 1\nsteps: {some-step: {directory: choice}}", "Python identifier"),
    ("version: 1\nsteps: {x: {directory: ../choice}}", "Python identifier"),
    ("version: 1\nsteps: {}\ncontext: {x: {type: string, minimum: 0}}", "minimum"),
    ("version: 1\nsteps: {}\ncontext: {x: {type: integer, default: true}}", "expected integer"),
    ("version: 1\nsteps: {}\ncontext: {x: {type: string, default: null}}", "expected string"),
    ("version: 1\nsteps: {}\ncontext: {x: {type: object, default: {}, fields: {y: {type: string}}}}",
     "default.y: field is required"),
])
def test_reject_invalid_manifests(tmp_path, yaml, message):
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml)
    with pytest.raises(ValueError, match=message) as caught:
        read_manifest(path)
    assert str(path) in str(caught.value)


@pytest.mark.parametrize(("addition", "message"), [
    ("start_at: count", "exactly one start_at"),
    ("reset_on_return_to_menu: [private]", "unknown field 'private'"),
    ("context_dependencies: {buy_package: [private]}", "unknown field 'private'"),
])
def test_reject_invalid_registry_links(workflow_tree, addition, message):
    manifest = workflow_tree / "probe" / "workflow.yaml"
    manifest.write_text(PROBE_MANIFEST + addition + "\n")
    with pytest.raises(ValueError, match=message) as caught:
        build_registry(workflow_tree)
    assert str(manifest) in str(caught.value)


def test_reject_unresolved_destination(workflow_tree):
    manifest = workflow_tree / "probe" / "workflow.yaml"
    manifest.write_text(PROBE_MANIFEST.replace("step: menu", "step: absent"))
    with pytest.raises(ValueError, match=r"probe/workflow.yaml: destinations.menu"):
        build_registry(workflow_tree)


def test_reject_undeclared_step_and_missing_instruction(workflow_tree):
    step = workflow_tree / "probe" / "record_count"
    stray = step.with_name("stray")
    stray.mkdir()
    (stray / "main.py").touch()
    with pytest.raises(ValueError, match="steps missing declarations for stray"):
        build_registry(workflow_tree)
    shutil.rmtree(stray)
    (step / "instruction.md").unlink()
    with pytest.raises(ValueError, match=r"probe/workflow.yaml: workflow.probe.record_count.main: .*instruction.md"):
        build_registry(workflow_tree)


def test_reject_collision_with_global_tool(workflow_tree):
    step = workflow_tree / "probe" / "record_count" / "main.py"
    step.write_text(PROBE_STEP + '\nrecord_count.__name__ = "request_return_to_landing"\n')
    with pytest.raises(ValueError, match=r"global.main: duplicate MCP tool .*probe/workflow.yaml"):
        build_registry(workflow_tree)


async def test_new_workflow_executes_from_manifest(workflow_tree, engine):
    manifest = workflow_tree / "landing" / "workflow.yaml"
    manifest.write_text(manifest.read_text().replace(
        "preferences: {workflow: buy_package, step: preferences}", "preferences: {workflow: probe, step: count}",
    ))
    registry = build_registry(workflow_tree)
    engine = Engine(Conversations(engine.conversations.redis, registry), engine.accounts, registry)
    engine.accounts.post.return_value = {"outcome": "name_recorded"}

    for session in ("one", "two"):
        async def invoke(tool, **arguments):
            return await engine.invoke(session, "wallet", tool, arguments, turn=tool)

        await invoke("record_name", revision=0, name="Ari")
        routed = await invoke("select_service", revision=1, service="buy_package")
        assert (routed["state"], routed["step"]) == ("probe", "record_count")
        assert routed["instruction"]["question"] == "Count one item."
        assert routed["instruction"]["context"] == {"display_name": "Ari"}

        c = await engine.conversations.read(session, "wallet")
        scope = WorkflowAccess(registry, c, "probe")
        context = scope.context()
        context["counter"]["count"] = 99
        assert context["counter"]["count"] == 0
        with pytest.raises(ValueError, match="expected boolean"):
            context["counter"] = {"count": 0, "ready": 1}
        with pytest.raises(KeyError, match="Undeclared context dependency"):
            scope.context("start")

        returned = await invoke("record_count", revision=2)
        assert returned["outcome"] == "counted" and returned["step"] == "intent_classification"
        c = await engine.conversations.read(session, "wallet")
        assert WorkflowAccess(registry, c, "probe").context()["counter"] == {"count": 1, "ready": False}
