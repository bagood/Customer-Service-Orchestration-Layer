"""Classify intent using a configurable OpenAI-compatible Chat Completions API."""

import json
from importlib import import_module
from importlib.resources import files
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.config import Settings

Intent = import_module("workflow-config.landing").Intent


class DecisionModelError(Exception):
    """A sanitized provider/configuration failure that must not update workflow state."""


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent | None
    reason: Literal["recognized", "ambiguous", "unsupported"]

    @model_validator(mode="after")
    def validate_recognized_intent(self) -> "IntentDecision":
        if (self.reason == "recognized") != (self.intent is not None):
            raise ValueError("A recognized decision must contain exactly one supported intent")
        return self


class DecisionModel:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.instructions = (
            files("workflow-tools.landing")
            .joinpath("instructions/intent_classification.md")
            .read_text(encoding="utf-8")
            .strip()
        )
        if not self.instructions:
            raise ValueError("Intent classification instructions must not be empty")

    async def classify(self, message: str, prior_message: str | None = None) -> IntentDecision:
        settings = self.settings
        if not settings.llm_base_url or not settings.llm_model:
            raise DecisionModelError(
                "Configure MCP_LLM_BASE_URL and MCP_LLM_MODEL for classification"
            )

        schema = IntentDecision.model_json_schema()
        response_format = {"type": settings.llm_response_format}
        if settings.llm_response_format == "json_schema":
            response_format["json_schema"] = {
                "name": "intent_decision",
                "strict": True,
                "schema": schema,
            }
        headers = {}
        if settings.llm_api_key and settings.llm_api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {settings.llm_api_key.get_secret_value()}"
        payload = {
            "model": settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": self.instructions + "\nJSON schema: " + json.dumps(schema),
                },
                {
                    "role": "user",
                    "content": json.dumps({"message": message, "prior_message": prior_message}),
                },
            ],
            "response_format": response_format,
            "stream": False,
        }
        url = str(settings.llm_base_url).rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException:
            raise DecisionModelError(
                "Intent classification timed out; workflow state is unchanged"
            ) from None
        except httpx.HTTPStatusError as exc:
            raise DecisionModelError(
                f"Intent provider returned HTTP {exc.response.status_code}; "
                "workflow state is unchanged"
            ) from None
        except httpx.RequestError:
            raise DecisionModelError(
                "Intent provider is unreachable; workflow state is unchanged"
            ) from None

        try:
            choice = response.json()["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise ValueError("Invalid completion envelope")
            if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                raise ValueError("Incomplete or refused provider response")
            return IntentDecision.model_validate_json(choice["message"]["content"], strict=True)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            raise DecisionModelError(
                "Intent provider returned an invalid decision; workflow state is unchanged"
            ) from None
