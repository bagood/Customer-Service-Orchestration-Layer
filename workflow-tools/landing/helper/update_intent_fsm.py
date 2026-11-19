"""Validate an intent decision and produce the next immutable landing state."""

from importlib import import_module

from .decision_model import IntentDecision

_models = import_module("workflow-config.landing")
LandingState = _models.LandingState
LandingPhase = _models.LandingPhase


def update_intent_fsm(
    state: LandingState, decision: IntentDecision, message_id: str
) -> LandingState:
    """Allow only unresolved landing sessions to accept a validated model decision."""
    if state.phase == LandingPhase.INTENT_CLASSIFIED:
        raise ValueError("This session's intent is already classified")
    phase = (
        LandingPhase.INTENT_CLASSIFIED
        if decision.intent is not None
        else LandingPhase.NEEDS_CLARIFICATION
    )
    return LandingState.model_validate(
        {
            **state.model_dump(),
            "phase": phase,
            "intent": decision.intent,
            "version": state.version + 1,
            "last_message_id": message_id,
        }
    )
