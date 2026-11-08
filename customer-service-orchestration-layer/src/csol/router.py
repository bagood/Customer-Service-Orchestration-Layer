"""Deterministic route matching for IDLE sessions only."""

import re

from csol.config import RouteConfig, normalize
from csol.models import WorkflowId


def match_intents(message: str, config: RouteConfig) -> list[WorkflowId]:
    normalized = normalize(message)
    return [
        workflow
        for workflow, phrases in config.routes.items()
        if any(
            re.search(r"(?<!\w)" + re.escape(normalize(phrase)) + r"(?!\w)", normalized)
            for phrase in phrases
        )
    ]
