"""Strict wire contract for the Stage 01 menu-only tool."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"\S")
]
Message = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=1000, pattern=r"\S")
]
ErrorCode = Literal["INVALID_ARGUMENTS", "SERVER_UNAVAILABLE", "UNKNOWN_TOOL"]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


class TurnInput(StrictModel):
    session_ref: Identifier
    message_id: Identifier
    message: Message


class TurnResponse(StrictModel):
    # Invalid arguments cannot always supply a valid session reference.
    session_ref: Identifier | None
    mode: Literal["demo", "error"]
    state: Literal["MENU", "UNAVAILABLE"]
    state_version: Literal[0]
    customer_reply: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    allowed_actions: list[Literal["buy_package", "send_credit"]] = Field(max_length=2)
    transaction: None
    simulated: Literal[True]
    safe_to_display: Literal[True]
    error_code: ErrorCode | None = None
