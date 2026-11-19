"""Expose landing intent classification and coordinate atomic session updates."""

import asyncio
import hashlib
from importlib import import_module
from importlib.resources import files
from typing import Annotated, Literal

import yaml
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

from .helper.decision_model import DecisionModel, DecisionModelError
from .helper.update_intent_fsm import update_intent_fsm

_models = import_module("workflow-config.landing")
Intent = _models.Intent
LandingPhase = _models.LandingPhase
LandingState = _models.LandingState
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Message = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["classified", "needs_clarification"]
    state: LandingState
    next_workflow: Intent | None
    next_step: Literal["ask_customer", "handoff_pending"]
    customer_reply: str


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["classify_intent"]
    description: str = Field(min_length=1)


class ToolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow: Literal["landing"]
    tools: list[ToolDefinition] = Field(min_length=1, max_length=1)


class IntentClassifier:
    """Single-process demo state. No transactions or customer authentication are implemented."""

    def __init__(self, model: DecisionModel) -> None:
        self.model = model
        self._states: dict[str, LandingState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._results: dict[tuple[str, str], tuple[str, ClassificationResult]] = {}
        self._prior_messages: dict[str, str] = {}

    def get_state(self, session_ref: str) -> LandingState:
        return self._states.get(session_ref, LandingState(session_ref=session_ref))

    async def classify_intent(
        self, session_ref: Identifier, message_id: Identifier, message: Message
    ) -> ClassificationResult:
        """Classify one landing message and update its state only after a valid decision."""
        if session_ref not in self._locks:
            if len(self._locks) >= 1000:
                raise ToolError("Landing session capacity reached")
            self._locks[session_ref] = asyncio.Lock()
        fingerprint = hashlib.sha256(message.encode("utf-8")).hexdigest()
        async with self._locks[session_ref]:
            key = (session_ref, message_id)
            cached = self._results.get(key)
            if cached:
                if cached[0] != fingerprint:
                    raise ToolError("message_id was already used for a different message")
                return cached[1]
            state = self.get_state(session_ref)
            if state.phase == LandingPhase.INTENT_CLASSIFIED:
                raise ToolError(
                    "Session intent is already classified; landing cannot reclassify it"
                )
            if state.version >= 32:
                raise ToolError("Landing clarification limit reached")
            try:
                decision = await self.model.classify(message, self._prior_messages.get(session_ref))
            except DecisionModelError as exc:
                raise ToolError(str(exc)) from None
            updated = update_intent_fsm(state, decision, message_id)
            if updated.intent is None:
                reply = (
                    "Would you like to buy a telecom package or send prepaid credit "
                    "to another number? "
                    "Please choose one. / Apakah Anda ingin membeli paket atau transfer pulsa "
                    "ke nomor lain? Silakan pilih satu."
                )
                result = ClassificationResult(
                    status="needs_clarification",
                    state=updated,
                    next_workflow=None,
                    next_step="ask_customer",
                    customer_reply=reply,
                )
                self._prior_messages[session_ref] = message
            else:
                result = ClassificationResult(
                    status="classified",
                    state=updated,
                    next_workflow=updated.intent,
                    next_step="handoff_pending",
                    customer_reply=(
                        f"Your intent is {updated.intent.value}. The destination workflow "
                        "is not implemented yet. No purchase or transfer was performed."
                    ),
                )
                self._prior_messages.pop(session_ref, None)
            self._states[session_ref] = updated
            self._results[key] = (fingerprint, result)
            return result


def load_landing_instructions() -> str:
    """Read instructions for the landing workflow at server startup."""
    instructions = (
        files("workflow-config.landing")
        .joinpath("instructions.md")
        .read_text(encoding="utf-8")
        .strip()
    )
    if not instructions:
        raise ValueError("Landing workflow instructions must not be empty")
    return instructions


def register_landing_tools(server: MCPServer, settings: Settings) -> IntentClassifier:
    """Read the workflow's tool manifest and register its supported handler."""
    config = files("workflow-config.landing")
    manifest = ToolManifest.model_validate(
        yaml.safe_load(config.joinpath("tools.yaml").read_text(encoding="utf-8"))
    )
    classifier = IntentClassifier(DecisionModel(settings))
    for tool in manifest.tools:
        server.add_tool(classifier.classify_intent, name=tool.name, description=tool.description)
    return classifier
