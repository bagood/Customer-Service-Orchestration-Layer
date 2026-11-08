"""Controller-owned routing and package-purchase FSM; all balances are simulated."""

import json
import re
import sqlite3

from csol.config import Configuration, normalize
from csol.mock_transactions import _mock_buy_package
from csol.models import (
    ENTRY_STATES, PurchaseData, PurchaseTransaction, SessionState, TurnInput, TurnResponse,
)
from csol.router import match_intents
from csol.store import Session, Store

MENU_REPLY = (
    "Telecom demo menu (simulation only):\n"
    "1. Beli paket / buy package (buy_package)\n"
    "2. Transfer pulsa / send credit (send_credit)\n"
    "This menu turn does not execute a transaction."
)
AMBIGUOUS_REPLY = (
    "You requested both demo workflows. Which one would you like to do first?\n" + MENU_REPLY
)
FEEDBACK_REPLY = (
    "Please rate this demo from 1 to 5. Feedback collection is not available yet. "
    "Type cancel or batal to return to the menu."
)
UNRESOLVED_REPLY = (
    "The demo purchase outcome is unresolved. It will not be retried automatically. "
    "Type cancel or batal to return to the menu."
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
            transaction = None

            if normalize(turn.message) in {"cancel", "batal"}:
                event = "cancelled"
                session = self._cancel(before)
                reply = "Demo workflow cancelled.\n" + MENU_REPLY
            elif before.active_workflow == "buy_package":
                session, event, reply, transaction = self._purchase_turn(
                    connection, before, turn.message,
                )
            elif before.state != "IDLE":
                # Credit-transfer steps belong to Stage 04.
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
                transaction=transaction,
                simulated=True,
                safe_to_display=True,
            )
            self.store.record_event(connection, event, before, saved)
            return response

    def _validate_session(self, session: Session) -> None:
        # YAML cannot authorize new states or transitions. Persisted unsupported
        # workflow versions and inconsistent rows fail closed as unavailable.
        if session.active_workflow is None:
            if session.state != "IDLE" or session.version is not None or json.loads(session.data_json) != {}:
                raise ValueError("Inconsistent idle session")
            return
        if session.version != self.config.workflows[session.active_workflow].version:
            raise ValueError("Unsupported saved workflow state or version")
        if session.state == ENTRY_STATES[session.active_workflow]:
            if json.loads(session.data_json) != {}:
                raise ValueError("Entry state must not contain purchase data")
            return
        if session.active_workflow != "buy_package" or session.state not in {
            "ENTER_BALANCE", "CONFIRM_PURCHASE", "FEEDBACK",
        }:
            raise ValueError("Unsupported saved workflow state")
        data = self._purchase_data(session)
        if session.state == "ENTER_BALANCE":
            if data.balance_idr is not None or data.transaction_id is not None:
                raise ValueError("Balance entry cannot contain confirmation or transaction data")
        else:
            if data.balance_idr is None or data.balance_idr < self._price(data):
                raise ValueError("Purchase requires a sufficient saved simulation balance")
            if (session.state == "FEEDBACK") != (data.transaction_id is not None):
                raise ValueError("Transaction reference does not match purchase state")

    @staticmethod
    def _cancel(session: Session) -> Session:
        if session.state == "IDLE":
            return session
        return session.model_copy(update={
            "active_workflow": None, "version": None, "state": "IDLE",
            "state_version": session.state_version + 1, "data_json": "{}",
        })

    @staticmethod
    def _purchase_data(session: Session) -> PurchaseData:
        return PurchaseData.model_validate(json.loads(session.data_json))

    def _price(self, data: PurchaseData) -> int:
        return self.config.workflows["buy_package"].catalog[data.package].price_idr

    @staticmethod
    def _advance(session: Session, state: SessionState, data: PurchaseData) -> Session:
        return session.model_copy(update={
            "state": state, "state_version": session.state_version + 1,
            "data_json": data.model_dump_json(exclude_none=True),
        })

    @staticmethod
    def _transaction_key(session: Session, confirmation_revision: int) -> str:
        return f"buy_package:{session.session_id}:{session.version}:{confirmation_revision}"

    def _purchase_turn(
        self, connection: sqlite3.Connection, session: Session, message: str,
    ) -> tuple[Session, str, str, PurchaseTransaction | None]:
        token = normalize(message)
        if session.state == "SELECT_PACKAGE":
            package = {"a": "A", "b": "B", "1": "A", "2": "B"}.get(token)
            if package is None:
                return session, "entry_state_held", self._entry_reply(session), None
            selected = self._advance(session, "ENTER_BALANCE", PurchaseData(package=package))
            return selected, "package_selected", self._purchase_prompt(selected), None

        if session.state == "ENTER_BALANCE":
            data = self._purchase_data(session)
            # Check the original string: Unicode normalization must not turn
            # non-ASCII digits, separators, whitespace or decimals into money.
            if not re.fullmatch(r"[0-9]+", message):
                return session, "invalid_balance", self._purchase_prompt(session), None
            balance = int(message)
            if balance < self._price(data):
                return session, "insufficient_balance", (
                    "Insufficient typed demo balance. " + self._purchase_prompt(session)
                ), None
            confirmed = self._advance(
                session, "CONFIRM_PURCHASE", data.model_copy(update={"balance_idr": balance}),
            )
            return confirmed, "balance_accepted", self._purchase_prompt(confirmed), None

        if session.state == "CONFIRM_PURCHASE":
            if token in {"no", "tidak"}:
                return self._cancel(session), "purchase_declined", "Demo purchase cancelled.\n" + MENU_REPLY, None
            if token in {"yes", "ya"}:
                return self._execute_purchase(connection, session)
            if self.store.transaction_by_key(
                connection, self._transaction_key(session, session.state_version),
            ) is not None:
                return session, "purchase_unresolved", UNRESOLVED_REPLY, None
            return session, "confirmation_rejected", self._purchase_prompt(session), None

        # Feedback collection/reset is Stage 04. Repeated turns cannot execute.
        data = self._purchase_data(session)
        receipt = self._saved_receipt(connection, session, session.state_version - 2)
        if receipt.transaction_id != data.transaction_id:
            raise ValueError("Feedback transaction does not match the saved receipt")
        return session, "feedback_pending", FEEDBACK_REPLY, receipt

    def _execute_purchase(
        self, connection: sqlite3.Connection, session: Session,
    ) -> tuple[Session, str, str, PurchaseTransaction | None]:
        # Recheck every prerequisite at the only call site of the private mock.
        self._validate_session(session)
        if session.active_workflow != "buy_package" or session.state != "CONFIRM_PURCHASE":
            raise ValueError("Purchase execution requires the saved confirmation state")
        data = self._purchase_data(session)
        key = self._transaction_key(session, session.state_version)
        record, created = self.store.obtain_transaction(connection, key)
        executing = self._advance(
            session, "EXECUTE_PURCHASE", data.model_copy(update={"transaction_id": record["id"]}),
        )
        if created:
            try:
                result = PurchaseTransaction.model_validate(_mock_buy_package(record["id"]))
                if result.transaction_id != record["id"]:
                    raise ValueError("Mock returned a different transaction reference")
            except Exception:
                # Even the local mock must never turn an unknown outcome into
                # success or silently execute an existing transaction again.
                self.store.finish_transaction(connection, record["id"], succeeded=False)
                return session, "purchase_unresolved", UNRESOLVED_REPLY, None
            self.store.finish_transaction(connection, record["id"], succeeded=True)
        elif record["status"] != "SUCCEEDED":
            return session, "purchase_unresolved", UNRESOLVED_REPLY, None

        # Read the recorded outcome before constructing any success wording.
        receipt = self._saved_receipt(connection, session, session.state_version)
        completed = self._advance(executing, "FEEDBACK", self._purchase_data(executing))
        reply = (
            f"Demo purchase SUCCEEDED: Package {data.package} (Rp {self._price(data):,}), "
            f"transaction {receipt.transaction_id}. Simulation only; no real purchase "
            "or operator balance verification. " + FEEDBACK_REPLY
        )
        return completed, "purchase_succeeded", reply, receipt

    def _saved_receipt(
        self, connection: sqlite3.Connection, session: Session, confirmation_revision: int,
    ) -> PurchaseTransaction:
        record = self.store.transaction_by_key(
            connection, self._transaction_key(session, confirmation_revision),
        )
        if record is None or record["status"] != "SUCCEEDED":
            raise ValueError("A recorded SUCCEEDED transaction is required")
        return PurchaseTransaction(transaction_id=record["id"], status=record["status"])

    def _purchase_prompt(self, session: Session) -> str:
        data = self._purchase_data(session)
        package = f"Package {data.package} (Rp {self._price(data):,})"
        if session.state == "ENTER_BALANCE":
            return (
                f"{package} selected. Enter your typed simulation balance in IDR using "
                "ASCII digits 0-9 only. This is not a verified operator balance. "
                "Type cancel or batal to return to the menu. No transaction has been executed."
            )
        return (
            f"Confirm the demo purchase of {package} using the saved typed simulation balance? "
            "Reply exactly yes/ya to confirm or no/tidak to cancel. "
            "This is not a verified operator balance. No transaction has been executed."
        )

    def _entry_reply(self, session: Session) -> str:
        if session.active_workflow == "buy_package":
            catalog = self.config.workflows["buy_package"].catalog
            options = "; ".join(
                f"{name} Rp {package.price_idr:,}" for name, package in catalog.items()
            )
            prompt = f"Package demo selected. Catalog: {options}. Select A/B or 1/2."
        else:
            prompt = "Credit-transfer demo selected. Synthetic recipient entry is not available yet."
        return (
            prompt + " Type cancel or batal to return to the menu. "
            "No transaction has been executed."
        )
