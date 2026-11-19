"""Real HTTP provider checks. Run against the committed local Postman simulation."""

import asyncio
import json
import os
from importlib import import_module
from uuid import uuid4

import httpx
import pytest
from mcp import Client

from app.config import Settings
from app.mcp_server import create_mcp_server

landing = import_module("workflow-tools.landing.intent_classifier")
decision_models = import_module("workflow-tools.landing.helper.decision_model")


@pytest.fixture
def provider_url():
    url = os.environ.get("MCP_TEST_PROVIDER_URL")
    if not url:
        pytest.skip("Start the Postman simulation and set MCP_TEST_PROVIDER_URL to its /llm/v1 URL")
    return url


def settings_for(url, model="sim-default", **kwargs):
    return Settings(
        _env_file=None, llm_base_url=url, llm_model=model, llm_api_key="test-secret", **kwargs
    )


@pytest.mark.anyio
@pytest.mark.parametrize("format", ["json_object", "json_schema"])
async def test_mcp_classification_context_and_retries(provider_url, format):
    async with httpx.AsyncClient() as http:
        before = len((await http.get(provider_url.removesuffix("/v1") + "/__requests")).json())
    server = create_mcp_server(settings_for(provider_url, llm_response_format=format))
    session = uuid4().hex
    async with Client(server) as client:

        async def classify(message_id, message):
            return await client.call_tool(
                "classify_intent",
                {
                    "session_ref": session,
                    "message_id": message_id,
                    "message": message,
                },
            )

        unclear = await classify("m1", "Both please")
        assert not unclear.is_error
        assert unclear.structured_content["status"] == "needs_clarification"
        assert unclear.structured_content["state"]["intent"] is None
        result, retry = await asyncio.gather(
            classify("m2", "The first option"), classify("m2", "The first option")
        )
        assert not result.is_error
        assert result.structured_content == retry.structured_content
        assert result.structured_content["state"]["version"] == 2
        assert result.structured_content["next_workflow"] == "buy_package"
        assert result.structured_content["next_step"] == "handoff_pending"
        assert (await classify("m2", "A different message")).is_error
        assert (await classify("m3", "Saya mau transfer pulsa")).is_error
    async with httpx.AsyncClient() as http:
        requests = (await http.get(provider_url.removesuffix("/v1") + "/__requests")).json()
    # Find our follow-up request and prove the prior unresolved message went over HTTP.
    requests = requests[before:]
    assert len(requests) == 2
    assert all(request["hasAuthorization"] for request in requests)
    followups = [
        request
        for request in requests
        if json.loads(request["messages"][1]["content"])["message"] == "The first option"
        and request["response_format"]["type"] == format
    ]
    assert len(followups) == 1
    assert json.loads(followups[-1]["messages"][1]["content"])["prior_message"] == "Both please"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message,intent",
    [
        ("I want to buy data", "buy_package"),
        ("Saya mau transfer pulsa", "send_credit"),
        ("hello", None),
    ],
)
async def test_supported_and_unsupported_requests(provider_url, message, intent):
    classifier = landing.IntentClassifier(decision_models.DecisionModel(settings_for(provider_url)))
    result = await classifier.classify_intent(uuid4().hex, "m1", message)
    assert result.state.intent == intent
    assert result.status == ("classified" if intent else "needs_clarification")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scenario",
    [
        "500",
        "429",
        "invalid",
        "extra",
        "inconsistent",
        "malformed",
        "refusal",
        "truncated",
        "envelope",
        "timeout",
    ],
)
async def test_provider_failures_do_not_mutate_state(provider_url, scenario):
    model = decision_models.DecisionModel(
        settings_for(
            provider_url,
            model=f"sim-{scenario}",
            llm_timeout_seconds=0.1 if scenario == "timeout" else 5,
        )
    )
    classifier = landing.IntentClassifier(model)
    session = uuid4().hex
    with pytest.raises(landing.ToolError) as error:
        await classifier.classify_intent(session, "m1", "I want to buy data")
    assert "test-secret" not in str(error.value)
    assert classifier.get_state(session).version == 0
    assert classifier.get_state(session).intent is None
    classifier.model = decision_models.DecisionModel(settings_for(provider_url))
    result = await classifier.classify_intent(session, "m1", "I want to buy data")
    assert result.state.version == 1
