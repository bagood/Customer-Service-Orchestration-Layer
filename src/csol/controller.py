"""Controller-owned telecom FSMs and feedback; all transactions are simulated."""

import json
import logging
import re
import sqlite3
from collections.abc import Callable

from csol.config import Configuration, normalize
from csol.mock_transactions import TestOutcome, _mock_buy_package, _mock_send_credit
from csol.models import (
    ENTRY_STATES, MAX_MONEY_IDR, MockResult, PurchaseData, PurchaseTransaction,
    SessionState, TransferData, TurnInput, TurnResponse,
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
    "Please rate this demo from 1 to 5, or type skip/lewati to skip feedback "
    "and return to the menu. Type cancel or batal to skip and return as well."
)
UNRESOLVED_REPLY = (
    "The demo transaction is pending manual review; its outcome is unresolved. "
    "It will not be retried automatically. This workflow is held for review."
)
FAILED_REPLY = (
    "The demo transaction FAILED. It will not be retried automatically. "
    "Type cancel or batal to return to the menu."
)
LOGGER = logging.getLogger(__name__)
CONFIRMATION_STATES = {"CONFIRM_PURCHASE", "CONFIRM_TRANSFER"}


class Controller:
    def __init__(
        self, store: Store, config: Configuration, *, _test_mock_outcome: TestOutcome = "SUCCEEDED",
    ) -> None:
        self.store = store
        self.config = config
        # In-process test injection only: no tool field, environment setting or
        # customer text can select the mock's outcome.
        if _test_mock_outcome not in {"SUCCEEDED", "FAILED", "UNKNOWN", "TIMEOUT"}:
            raise ValueError("Unsupported test mock outcome")
        self._test_mock_outcome = _test_mock_outcome

    def process_turn(self, turn: TurnInput) -> TurnResponse:
        turn = TurnInput.model_validate(turn)
        token = normalize(turn.message)
        with self.store.transaction() as connection:
            before = self.store.get_or_create_session(connection, turn.session_ref)
            self._validate_session(before)
            recorded = self.store.recorded_response(connection, turn.session_ref, turn.message_id)
            if recorded is not None:
                return recorded

            reserved_id = None
            if before.state in CONFIRMATION_STATES and token in {"yes", "ya"}:
                key = self._transaction_key(before, before.state_version)
                record, created = self.store.obtain_transaction(connection, key)
                if created:
                    # Commit the PENDING fence BEFORE the private mock. A crash
                    # or failure in the final session/audit/cache commit must
                    # never erase evidence that invocation may have happened.
                    connection.commit()
                    connection.execute("BEGIN IMMEDIATE")
                    current = self.store.get_or_create_session(connection, turn.session_ref)
                    self._validate_session(current)
                    if self._prerequisites(current) != self._prerequisites(before):
                        raise ValueError("Saved prerequisites changed after reservation")
                    before = current
                    recorded = self.store.recorded_response(connection, turn.session_ref, turn.message_id)
                    if recorded is not None:
                        # A concurrent repeat recorded a conservative pending
                        # reply in the gap. Preserve it and leave review required.
                        return recorded
                    reserved_id = record["id"]
            session = before
            reply = MENU_REPLY
            transaction = None
            held = False
            record = None
            if before.state in CONFIRMATION_STATES:
                record = self.store.transaction_by_key(
                    connection, self._transaction_key(before, before.state_version),
                )
                if record is not None and record["status"] not in {
                    "PENDING", "SUCCEEDED", "FAILED", "UNKNOWN",
                }:
                    raise ValueError("Invalid recorded transaction status")

            if (record is not None and record["id"] != reserved_id
                    and record["status"] in {"PENDING", "UNKNOWN"}):
                held = True
                event, reply = "transaction_review_required", UNRESOLVED_REPLY
            elif (record is not None and record["status"] == "FAILED"
                  and token not in {"cancel", "batal", "no", "tidak"}):
                event, reply = "transaction_failed", FAILED_REPLY
            elif before.state == "FEEDBACK":
                session, event, reply, transaction = self._feedback_turn(
                    connection, before, turn.message,
                )
            elif token in {"cancel", "batal"}:
                event = "cancelled"
                session = self._cancel(before)
                reply = "Demo workflow cancelled.\n" + MENU_REPLY
            elif before.active_workflow == "buy_package":
                session, event, reply, transaction = self._purchase_turn(
                    connection, before, turn.message, reserved_id,
                )
            elif before.active_workflow == "send_credit":
                session, event, reply, transaction = self._transfer_turn(
                    connection, before, turn.message, reserved_id,
                )
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
            saved = self.store.save_session(
                connection, session, expected_state_version=before.state_version,
            )
            held = held or reply == UNRESOLVED_REPLY
            response = TurnResponse(
                session_ref=saved.session_id,
                mode=saved.active_workflow or "demo",
                state=saved.state,
                state_version=saved.state_version,
                customer_reply=reply,
                allowed_actions=([] if held else ["cancel"] if saved.active_workflow
                                 else ["buy_package", "send_credit"]),
                transaction=transaction,
                simulated=True,
                safe_to_display=True,
            )
            self.store.record_event(connection, event, before, saved)
            self.store.record_response(connection, turn.message_id, response)
        # Fixed event codes and controller-owned states only; no message,
        # message ID, session reference, recipient, balance or token in logs.
        LOGGER.info(
            "CSOL event=%s from=%s to=%s revision=%s",
            event, before.state, saved.state, saved.state_version,
        )
        return response

    @staticmethod
    def _prerequisites(session: Session) -> tuple:
        return (
            session.active_workflow, session.version, session.state,
            session.state_version, session.data_json,
        )

    def _validate_session(self, session: Session) -> None:
        # YAML cannot authorize new states or transitions. Persisted unsupported
        # workflow versions and inconsistent rows fail closed as unavailable.
        Session.model_validate(session)
        if session.state_version > 2**63 - 4:
            raise ValueError("Saved state revision exhausted")
        if session.active_workflow is None:
            if session.state != "IDLE" or session.version is not None or json.loads(session.data_json) != {}:
                raise ValueError("Inconsistent idle session")
            return
        if session.version != self.config.workflows[session.active_workflow].version:
            raise ValueError("Unsupported saved workflow state or version")
        minimum_revision = {
            "buy_package": {"SELECT_PACKAGE": 1, "ENTER_BALANCE": 2, "CONFIRM_PURCHASE": 3, "FEEDBACK": 5},
            "send_credit": {"ENTER_MSISDN": 1, "ENTER_AMOUNT": 2, "ENTER_BALANCE": 3, "CONFIRM_TRANSFER": 4, "FEEDBACK": 6},
        }[session.active_workflow].get(session.state)
        if minimum_revision is None or session.state_version < minimum_revision:
            raise ValueError("Invalid saved state revision")
        if session.state == ENTRY_STATES[session.active_workflow]:
            if json.loads(session.data_json) != {}:
                raise ValueError("Entry state must not contain workflow data")
            return

        if session.active_workflow == "buy_package":
            if session.state not in {"ENTER_BALANCE", "CONFIRM_PURCHASE", "FEEDBACK"}:
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
        else:
            if session.state not in {"ENTER_AMOUNT", "ENTER_BALANCE", "CONFIRM_TRANSFER", "FEEDBACK"}:
                raise ValueError("Unsupported saved workflow state")
            transfer = self._transfer_data(session)
            if session.state == "ENTER_AMOUNT":
                if any(value is not None for value in (
                    transfer.amount_idr, transfer.balance_idr, transfer.transaction_id,
                )):
                    raise ValueError("Amount entry may only contain the recipient")
            else:
                if transfer.amount_idr is None:
                    raise ValueError("Transfer requires a positive saved amount")
                if session.state == "ENTER_BALANCE":
                    if transfer.balance_idr is not None or transfer.transaction_id is not None:
                        raise ValueError("Balance entry cannot contain confirmation or transaction data")
                else:
                    if transfer.balance_idr is None or transfer.balance_idr < transfer.amount_idr:
                        raise ValueError("Transfer requires a sufficient saved simulation balance")
                    if (session.state == "FEEDBACK") != (transfer.transaction_id is not None):
                        raise ValueError("Transaction reference does not match transfer state")

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

    @staticmethod
    def _transfer_data(session: Session) -> TransferData:
        return TransferData.model_validate(json.loads(session.data_json))

    @staticmethod
    def _ascii_integer(message: str) -> int | None:
        # Inspect the raw input; Unicode normalization must not turn other
        # digit alphabets, whitespace, signs or separators into money.
        if len(message) > 10 or re.fullmatch(r"[0-9]+", message) is None:
            return None
        value = int(message)
        return value if value <= MAX_MONEY_IDR else None

    def _price(self, data: PurchaseData) -> int:
        return self.config.workflows["buy_package"].catalog[data.package].price_idr

    @staticmethod
    def _advance(session: Session, state: SessionState, data: PurchaseData | TransferData) -> Session:
        return session.model_copy(update={
            "state": state, "state_version": session.state_version + 1,
            "data_json": data.model_dump_json(exclude_none=True),
        })

    @staticmethod
    def _transaction_key(session: Session, confirmation_revision: int) -> str:
        return f"{session.active_workflow}:{session.session_id}:{session.version}:{confirmation_revision}"

    def _purchase_turn(
        self, connection: sqlite3.Connection, session: Session, message: str, reserved_id: int | None,
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
            balance = self._ascii_integer(message)
            if balance is None:
                return session, "invalid_balance", self._purchase_prompt(session), None
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
                return self._execute_purchase(connection, session, reserved_id)
            if self.store.transaction_by_key(
                connection, self._transaction_key(session, session.state_version),
            ) is not None:
                return session, "purchase_unresolved", UNRESOLVED_REPLY, None
            return session, "confirmation_rejected", self._purchase_prompt(session), None

        raise ValueError("Unsupported purchase state")

    def _transfer_turn(
        self, connection: sqlite3.Connection, session: Session, message: str, reserved_id: int | None,
    ) -> tuple[Session, str, str, PurchaseTransaction | None]:
        if session.state == "ENTER_MSISDN":
            # Illustrative synthetic format: 08 followed by 8-11 ASCII digits,
            # with equivalent 628 and +628 forms. No ownership verification.
            match = re.fullmatch(r"(?:08|628|\+628)([0-9]{8,11})", message)
            if match is None:
                return session, "entry_state_held", self._entry_reply(session), None
            recipient = self._advance(
                session, "ENTER_AMOUNT", TransferData(msisdn="628" + match[1]),
            )
            return recipient, "recipient_accepted", self._transfer_prompt(recipient), None

        data = self._transfer_data(session)
        if session.state == "ENTER_AMOUNT":
            amount = self._ascii_integer(message)
            if amount is None or amount == 0:
                return session, "invalid_amount", self._transfer_prompt(session), None
            collected = self._advance(
                session, "ENTER_BALANCE", data.model_copy(update={"amount_idr": amount}),
            )
            return collected, "amount_accepted", self._transfer_prompt(collected), None

        if session.state == "ENTER_BALANCE":
            balance = self._ascii_integer(message)
            if balance is None:
                return session, "invalid_balance", self._transfer_prompt(session), None
            if balance < data.amount_idr:
                return session, "insufficient_balance", (
                    "Insufficient typed demo balance. " + self._transfer_prompt(session)
                ), None
            confirmed = self._advance(
                session, "CONFIRM_TRANSFER", data.model_copy(update={"balance_idr": balance}),
            )
            return confirmed, "balance_accepted", self._transfer_prompt(confirmed), None

        if session.state == "CONFIRM_TRANSFER":
            token = normalize(message)
            if token in {"no", "tidak"}:
                return self._cancel(session), "transfer_declined", "Demo transfer cancelled.\n" + MENU_REPLY, None
            if token in {"yes", "ya"}:
                return self._execute_transfer(connection, session, reserved_id)
            if self.store.transaction_by_key(
                connection, self._transaction_key(session, session.state_version),
            ) is not None:
                return session, "transfer_unresolved", UNRESOLVED_REPLY, None
            return session, "confirmation_rejected", self._transfer_prompt(session), None

        raise ValueError("Unsupported transfer state")

    def _feedback_turn(
        self, connection: sqlite3.Connection, session: Session, message: str,
    ) -> tuple[Session, str, str, PurchaseTransaction | None]:
        data = (self._purchase_data(session) if session.active_workflow == "buy_package"
                else self._transfer_data(session))
        receipt = self._saved_receipt(connection, session, session.state_version - 2)
        if receipt.transaction_id != data.transaction_id:
            raise ValueError("Feedback transaction does not match the saved receipt")
        rating = int(message) if re.fullmatch(r"[1-5]", message) else None
        skipped = normalize(message) in {"skip", "lewati", "cancel", "batal"}
        if rating is None and not skipped:
            return session, "feedback_pending", FEEDBACK_REPLY, receipt
        self.store.record_feedback(connection, session.session_id, rating)
        reply = "Demo feedback skipped.\n" if skipped else "Thank you for rating this demo.\n"
        event = "feedback_skipped" if skipped else "feedback_recorded"
        return self._cancel(session), event, reply + MENU_REPLY, None

    def _execute_transfer(
        self, connection: sqlite3.Connection, session: Session, reserved_id: int | None,
    ) -> tuple[Session, str, str, PurchaseTransaction | None]:
        self._validate_session(session)
        if session.active_workflow != "send_credit" or session.state != "CONFIRM_TRANSFER":
            raise ValueError("Transfer execution requires the saved confirmation state")
        data = self._transfer_data(session)
        key = self._transaction_key(session, session.state_version)
        record = self._run_reserved_mock(connection, session, key, reserved_id, _mock_send_credit)
        executing = self._advance(
            session, "EXECUTE_TRANSFER", data.model_copy(update={"transaction_id": record["id"]}),
        )
        if record["status"] == "FAILED":
            return session, "transfer_failed", FAILED_REPLY, None
        if record["status"] != "SUCCEEDED":
            return session, "transfer_unresolved", UNRESOLVED_REPLY, None

        receipt = self._saved_receipt(connection, session, session.state_version)
        completed = self._advance(executing, "FEEDBACK", self._transfer_data(executing))
        reply = (
            f"Demo transfer SUCCEEDED: Rp {data.amount_idr:,} to {self._masked_recipient(data)}, "
            f"transaction {receipt.transaction_id}. Simulation only; no real credit movement "
            "or operator balance verification. " + FEEDBACK_REPLY
        )
        return completed, "transfer_succeeded", reply, receipt

    def _execute_purchase(
        self, connection: sqlite3.Connection, session: Session, reserved_id: int | None,
    ) -> tuple[Session, str, str, PurchaseTransaction | None]:
        # Recheck every prerequisite at the only call site of the private mock.
        self._validate_session(session)
        if session.active_workflow != "buy_package" or session.state != "CONFIRM_PURCHASE":
            raise ValueError("Purchase execution requires the saved confirmation state")
        data = self._purchase_data(session)
        key = self._transaction_key(session, session.state_version)
        record = self._run_reserved_mock(connection, session, key, reserved_id, _mock_buy_package)
        executing = self._advance(
            session, "EXECUTE_PURCHASE", data.model_copy(update={"transaction_id": record["id"]}),
        )
        if record["status"] == "FAILED":
            return session, "purchase_failed", FAILED_REPLY, None
        if record["status"] != "SUCCEEDED":
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

    def _run_reserved_mock(
        self, connection: sqlite3.Connection, session: Session, key: str,
        reserved_id: int | None, operation: Callable[..., object],
    ) -> sqlite3.Row:
        # Re-read under the write lock immediately before invocation. The model
        # cannot supply a reservation ID, state, version or saved prerequisites.
        saved = self.store.get_or_create_session(connection, session.session_id)
        self._validate_session(saved)
        if self._prerequisites(saved) != self._prerequisites(session):
            raise ValueError("Execution requires matching saved prerequisites")
        record = self.store.transaction_by_key(connection, key)
        if record is None:
            raise ValueError("Execution requires a durable transaction reservation")
        if record["id"] == reserved_id and record["status"] == "PENDING":
            try:
                result = MockResult.model_validate(
                    operation(record["id"]) if self._test_mock_outcome == "SUCCEEDED"
                    else operation(record["id"], _test_outcome=self._test_mock_outcome)
                )
                if result.transaction_id != record["id"]:
                    raise ValueError("Mock returned a different transaction reference")
                status = result.status
            except Exception:
                status = "UNKNOWN"
            self.store.finish_transaction(connection, record["id"], status=status)
            finished = self.store.transaction_by_key(connection, key)
            if finished is None or finished["status"] != status:
                if status == "SUCCEEDED":
                    raise ValueError("A recorded SUCCEEDED transaction is required")
                raise ValueError("Transaction finalization did not persist")
            return finished
        return record

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

    @staticmethod
    def _masked_recipient(data: TransferData) -> str:
        return data.msisdn[:3] + "*" * (len(data.msisdn) - 7) + data.msisdn[-4:]

    def _transfer_prompt(self, session: Session) -> str:
        data = self._transfer_data(session)
        recipient = self._masked_recipient(data)
        if session.state == "ENTER_AMOUNT":
            return (
                f"Synthetic recipient {recipient} selected. Enter a positive demo transfer "
                "amount in IDR using ASCII digits 0-9 only. "
                "Type cancel or batal to return to the menu. No transaction has been executed."
            )
        if session.state == "ENTER_BALANCE":
            return (
                f"Demo transfer amount Rp {data.amount_idr:,} to {recipient}. Enter your typed "
                "simulation balance in IDR using ASCII digits 0-9 only. This is not a verified "
                "operator balance. Type cancel or batal to return to the menu. "
                "No transaction has been executed."
            )
        return (
            f"Confirm the demo transfer of Rp {data.amount_idr:,} to {recipient} using the saved "
            "typed simulation balance? Reply exactly yes/ya to confirm or no/tidak to cancel. "
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
            prompt = (
                "Credit-transfer demo selected. Enter a synthetic mobile recipient: 08 followed "
                "by 8-11 ASCII digits, or the equivalent 628... / +628... format. "
                "This is not proof of ownership; use synthetic test numbers only."
            )
        return (
            prompt + " Type cancel or batal to return to the menu. "
            "No transaction has been executed."
        )
