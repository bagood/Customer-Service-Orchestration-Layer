"""Load the two fixed, versioned workflow definitions; YAML is not executable."""

import re
import unicodedata
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator

from csol.models import ENTRY_STATES, SessionState, StrictModel, WorkflowId

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def normalize(text: str) -> str:
    """Normalize Unicode, case and whitespace without discarding word boundaries."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class RouteConfig(StrictModel):
    routes: dict[WorkflowId, list[str]]

    @model_validator(mode="after")
    def validate_routes(self) -> Self:
        if set(self.routes) != set(ENTRY_STATES):
            raise ValueError("Exactly the two supported route groups are required")
        seen = set()
        for phrases in self.routes.values():
            if not phrases:
                raise ValueError("Route groups must not be empty")
            for phrase in phrases:
                canonical = normalize(phrase)
                if not re.fullmatch(r"\w+(?: \w+)*", canonical) or canonical in seen:
                    raise ValueError("Route phrases must be distinct, nonempty words or phrases")
                seen.add(canonical)
        return self


class CatalogPackage(StrictModel):
    price_idr: int = Field(gt=0)


class WorkflowConfig(StrictModel):
    workflow: WorkflowId
    version: int = Field(ge=1, le=1)
    states: list[SessionState]
    catalog: dict[Literal["A", "B"], CatalogPackage]

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.states != [ENTRY_STATES[self.workflow]]:
            raise ValueError("Only the Python-defined entry state is supported in Stage 02")
        expected_catalog = {"A", "B"} if self.workflow == "buy_package" else set()
        if set(self.catalog) != expected_catalog:
            raise ValueError("Package catalog requires A/B; credit catalog must be empty")
        return self


class Configuration(StrictModel):
    routing: RouteConfig
    workflows: dict[WorkflowId, WorkflowConfig]


def load_configuration(config_dir: Path = DEFAULT_CONFIG_DIR) -> Configuration:
    """Fail startup on missing/malformed/unsupported definitions."""
    with (config_dir / "global.yaml").open(encoding="utf-8") as source:
        routing = RouteConfig.model_validate(yaml.safe_load(source))
    workflows = {}
    for workflow in ENTRY_STATES:
        with (config_dir / "workflows" / f"{workflow}.v1.yaml").open(encoding="utf-8") as source:
            definition = WorkflowConfig.model_validate(yaml.safe_load(source))
        if definition.workflow != workflow:
            raise ValueError("Workflow filename and definition must agree")
        workflows[workflow] = definition
    return Configuration(routing=routing, workflows=workflows)
