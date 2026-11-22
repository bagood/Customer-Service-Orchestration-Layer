from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from app.database import Accounts

START = ("start", "identification")
MENU = ("landing", "intent_classification")
PREFERENCES = ("buy_package", "package_preference_identification")
CONFIRM = ("buy_package", "user_confirmation")
DETOUR = ("buy_package", "buy_credits_confirmation")
CREDITS = ("buy_credits", "amount_of_balance")

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CreditAmount = Annotated[int, Field(ge=1, le=2**31 - 1)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Action(Input):
    revision: Annotated[int, Field(ge=0, description="Revision from the current CSOL instruction.")]


class Answer(Action):
    answer: Literal["yes", "no", "unclear"]


@dataclass
class Conversation:
    customer: str
    instance: str = field(default_factory=lambda: uuid4().hex)
    state: str = START[0]
    step: str = START[1]
    revision: int = 0
    display_name: str | None = None
    offer: dict | None = None
    offer_presented_turn: str | None = None
    shortfall: int | None = None
    return_question: dict | None = None
    in_flight: dict | None = None

    def move(self, destination):
        self.state, self.step = destination

    def clear_offer(self):
        self.offer = None
        self.offer_presented_turn = None
        self.shortfall = None

    @property
    def operation_id(self):
        return f"{self.instance}.{self.revision}"

    def dump(self):
        return asdict(self)


def wording(module_file):
    return Path(module_file).with_name("instruction.md").read_text().strip()


@dataclass(frozen=True)
class Step:
    instruction: Callable[[Conversation], str]
    action: Callable[[Conversation, Action, "Accounts", str], Awaitable[dict]]
    schema: type[Action]

    @property
    def names(self):
        return (self.instruction.__name__, self.action.__name__)
