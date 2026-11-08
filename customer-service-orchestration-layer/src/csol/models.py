"""Strict wire contract and Python-owned states for the telecom demo."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"\S")
]
Message = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=1000, pattern=r"\S")
]
ErrorCode = Literal["INVALID_ARGUMENTS", "SERVER_UNAVAILABLE", "UNKNOWN_TOOL"]
WorkflowId = Literal["buy_package", "send_credit"]
SessionState = Literal[
    "IDLE", "SELECT_PACKAGE", "ENTER_BALANCE", "CONFIRM_PURCHASE",
    "EXECUTE_PURCHASE", "FEEDBACK", "ENTER_MSISDN",
]

ENTRY_STATES: dict[WorkflowId, SessionState] = {
    "buy_package": "SELECT_PACKAGE",
    "send_credit": "ENTER_MSISDN",
}
WORKFLOW_STATES: dict[WorkflowId, list[SessionState]] = {
    "buy_package": [
        "SELECT_PACKAGE", "ENTER_BALANCE", "CONFIRM_PURCHASE", "EXECUTE_PURCHASE", "FEEDBACK",
    ],
    "send_credit": ["ENTER_MSISDN"],
}


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


class TurnInput(StrictModel):
    session_ref: Identifier
    message_id: Identifier
    message: Message


class PurchaseData(StrictModel):
    package: Literal["A", "B"]
    balance_idr: int | None = Field(default=None, ge=0)
    transaction_id: int | None = Field(default=None, gt=0)


class PurchaseTransaction(StrictModel):
    transaction_id: int = Field(gt=0)
    status: Literal["SUCCEEDED"]


class TurnResponse(StrictModel):
    # Invalid arguments cannot always supply a valid session reference.
    session_ref: Identifier | None
    mode: Literal["demo", "buy_package", "send_credit", "error"]
    # EXECUTE_PURCHASE is an internal transition, never a customer-facing state.
    state: Literal[
        "IDLE", "SELECT_PACKAGE", "ENTER_BALANCE", "CONFIRM_PURCHASE",
        "FEEDBACK", "ENTER_MSISDN", "UNAVAILABLE",
    ]
    state_version: int = Field(ge=0)
    customer_reply: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    allowed_actions: list[Literal["buy_package", "send_credit", "cancel"]] = Field(max_length=2)
    transaction: PurchaseTransaction | None
    simulated: Literal[True]
    safe_to_display: Literal[True]
    error_code: ErrorCode | None = None
