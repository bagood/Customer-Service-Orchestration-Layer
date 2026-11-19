"""Landing state invariants and controller behavior, independent of model accuracy."""

import asyncio
from importlib import import_module

import pytest
from pydantic import ValidationError

state_models = import_module("workflow-config.landing")
decisions = import_module("workflow-tools.landing.helper.decision_model")
updates = import_module("workflow-tools.landing.helper.update_intent_fsm")
landing = import_module("workflow-tools.landing.intent_classifier")


def test_state_rejects_unrecognized_intent_and_inconsistent_phase():
    with pytest.raises(ValidationError):
        state_models.LandingState(session_ref="s", intent="refund", phase="intent_classified")
    with pytest.raises(ValidationError):
        state_models.LandingState(session_ref="s", intent="buy_package")
    with pytest.raises(ValidationError):
        state_models.LandingState(session_ref="s", phase="intent_classified")


def test_only_valid_decisions_transition_state():
    state = state_models.LandingState(session_ref="s")
    ambiguous = decisions.IntentDecision(intent=None, reason="ambiguous")
    clarified = updates.update_intent_fsm(state, ambiguous, "m1")
    assert clarified.phase == "needs_clarification"
    assert state.version == 0
    decision = decisions.IntentDecision(intent="send_credit", reason="recognized")
    final = updates.update_intent_fsm(clarified, decision, "m2")
    assert final.intent == "send_credit"
    assert final.version == 2
    with pytest.raises(ValueError, match="already classified"):
        updates.update_intent_fsm(final, decision, "m3")
    with pytest.raises(ValidationError):
        decisions.IntentDecision(intent=None, reason="recognized")


class ScriptedModel:
    """Isolate state/concurrency tests; provider transport is tested in the simulation suite."""

    def __init__(self):
        self.calls = 0

    async def classify(self, message, prior_message=None):
        self.calls += 1
        await asyncio.sleep(0)
        return decisions.IntentDecision(intent="buy_package", reason="recognized")


@pytest.mark.anyio
async def test_concurrent_retries_are_deduplicated_and_sessions_are_isolated():
    model = ScriptedModel()
    classifier = landing.IntentClassifier(model)
    first, retry = await asyncio.gather(
        classifier.classify_intent("s1", "m1", "Buy a package"),
        classifier.classify_intent("s1", "m1", "Buy a package"),
    )
    assert first == retry
    assert model.calls == 1
    assert first.state.version == 1
    assert classifier.get_state("s2").intent is None
    with pytest.raises(landing.ToolError, match="different message"):
        await classifier.classify_intent("s1", "m1", "Send credit")
    with pytest.raises(landing.ToolError, match="already classified"):
        await classifier.classify_intent("s1", "m2", "Send credit")
    assert model.calls == 1


@pytest.mark.anyio
async def test_provider_failure_leaves_state_and_retry_identifier_available():
    class FailingModel:
        async def classify(self, *args):
            raise decisions.DecisionModelError("Provider unavailable")

    classifier = landing.IntentClassifier(FailingModel())
    with pytest.raises(landing.ToolError, match="Provider unavailable"):
        await classifier.classify_intent("s", "m", "Buy a package")
    assert classifier.get_state("s").version == 0
    classifier.model = ScriptedModel()
    result = await classifier.classify_intent("s", "m", "Buy a package")
    assert result.state.version == 1
