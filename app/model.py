from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from app.database import Accounts
    from app.registry import WorkflowAccess

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CreditAmount = Annotated[int, Field(ge=1, le=2**31 - 1)]
Position = tuple[str, str]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Action(Input):
    revision: Annotated[int, Field(ge=0, description="Revision from the current CSOL instruction.")]


class Answer(Action):
    answer: Literal["yes", "no", "unclear"]


@dataclass
class Conversation:
    customer: str
    state: str
    step: str
    instance: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    return_question: dict | None = None
    in_flight: dict | None = None
    _context: dict[str, dict] = field(default_factory=dict, repr=False)
    _stored: str | bytes | None = field(default=None, repr=False, compare=False)

    @property
    def position(self) -> Position:
        return self.state, self.step

    def move(self, destination: Position):
        self.state, self.step = destination

    @property
    def operation_id(self):
        return f"{self.instance}.{self.revision}"


@dataclass(frozen=True)
class Step:
    instruction: Callable[["WorkflowAccess"], str]
    action: Callable[[Conversation, Action, "Accounts", str, "WorkflowAccess"], Awaitable[dict]]
    schema: type[Action]

    @property
    def names(self):
        return self.instruction.__name__, self.action.__name__
