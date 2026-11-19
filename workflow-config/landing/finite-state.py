"""Validated state for identifying the customer's intended workflow."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Intent(StrEnum):
    BUY_PACKAGE = "buy_package"
    SEND_CREDIT = "send_credit"


class LandingPhase(StrEnum):
    AWAITING_INTENT = "awaiting_intent"
    NEEDS_CLARIFICATION = "needs_clarification"
    INTENT_CLASSIFIED = "intent_classified"


class LandingState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    workflow: Literal["landing"] = "landing"
    phase: LandingPhase = LandingPhase.AWAITING_INTENT
    intent: Intent | None = None
    version: int = Field(default=0, ge=0)
    last_message_id: str | None = None

    @model_validator(mode="after")
    def validate_intent_phase(self) -> "LandingState":
        if (self.phase == LandingPhase.INTENT_CLASSIFIED) != (self.intent is not None):
            raise ValueError("Only an intent_classified state may contain a supported intent")
        return self
