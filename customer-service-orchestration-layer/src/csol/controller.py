"""Controller-owned IDLE routing and cancel; workflow steps are not implemented."""

from csol.config import Configuration, normalize
from csol.models import ENTRY_STATES, TurnInput, TurnResponse
from csol.router import match_intents
from csol.store import Session, Store

MENU_REPLY = (
    "Telecom demo menu (simulation only):\n"
    "1. Beli paket / buy package (buy_package)\n"
    "2. Transfer pulsa / send credit (send_credit)\n"
    "No transaction has been executed."
)
AMBIGUOUS_REPLY = (
    "You requested both demo workflows. Which one would you like to do first?\n" + MENU_REPLY
)


class Controller:
    def __init__(self, store: Store, config: Configuration) -> None:
        self.store = store
        self.config = config

    def process_turn(self, turn: TurnInput) -> TurnResponse:
        turn = TurnInput.model_validate(turn)
        with self.store.transaction() as connection:
            before = self.store.get_or_create_session(connection, turn.session_ref)
            self._validate_session(before)
            session = before
            reply = MENU_REPLY

            if normalize(turn.message) in {"cancel", "batal"}:
                event = "cancelled"
                if before.state != "IDLE":
                    session = before.model_copy(update={
                        "active_workflow": None, "version": None, "state": "IDLE",
                        "state_version": before.state_version + 1, "data_json": "{}",
                    })
                reply = "Demo workflow cancelled.\n" + MENU_REPLY
            elif before.state != "IDLE":
                # Treat ordinary messages as responses to the saved entry state.
                # Selection/recipient validation belongs to Stages 03 and 04.
                event = "entry_state_held"
                reply = self._entry_reply(before)
            else:
                matches = match_intents(turn.message, self.config.routing)
                if len(matches) == 1:
                    workflow = matches[0]
                    session = before.model_copy(update={
                        "active_workflow": workflow,
                        "version": self.config.workflows[workflow].version,
                        "state": ENTRY_STATES[workflow],
                        "state_version": before.state_version + 1,
                    })
                    event = "workflow_started"
                    reply = self._entry_reply(session)
                elif len(matches) > 1:
                    event = "ambiguous_route"
                    reply = AMBIGUOUS_REPLY
                else:
                    event = "menu_shown"

            self._validate_session(session)
            saved = self.store.save_session(connection, session)
            response = TurnResponse(
                session_ref=saved.session_id,
                mode=saved.active_workflow or "demo",
                state=saved.state,
                state_version=saved.state_version,
                customer_reply=reply,
                allowed_actions=["cancel"] if saved.active_workflow else ["buy_package", "send_credit"],
                transaction=None,
                simulated=True,
                safe_to_display=True,
            )
            self.store.record_event(connection, event, before, saved)
            return response

    def _validate_session(self, session: Session) -> None:
        # YAML cannot authorize new states or transitions. Persisted unsupported
        # workflow versions and inconsistent rows fail closed as unavailable.
        if session.active_workflow is None:
            if session.state != "IDLE" or session.version is not None:
                raise ValueError("Inconsistent idle session")
        elif (
            session.state != ENTRY_STATES[session.active_workflow]
            or session.version != self.config.workflows[session.active_workflow].version
        ):
            raise ValueError("Unsupported saved workflow state or version")

    def _entry_reply(self, session: Session) -> str:
        if session.active_workflow == "buy_package":
            catalog = self.config.workflows["buy_package"].catalog
            options = "; ".join(
                f"{name} Rp {package.price_idr:,}" for name, package in catalog.items()
            )
            prompt = f"Package demo selected. Catalog: {options}. Package selection is not available yet."
        else:
            prompt = "Credit-transfer demo selected. Synthetic recipient entry is not available yet."
        return (
            prompt + " Type cancel or batal to return to the menu. "
            "No transaction has been executed."
        )
