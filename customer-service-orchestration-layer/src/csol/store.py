"""One persistent SQLite file for a single-process telecom simulation."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import Field

from csol.models import Identifier, SessionState, StrictModel, WorkflowId

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "csol.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    active_workflow TEXT,
    version INTEGER,
    state TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK (state_version >= 0),
    data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_messages (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    message_id TEXT NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY (session_id, message_id)
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    skipped INTEGER NOT NULL DEFAULT 0 CHECK (skipped IN (0, 1))
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    event_type TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


class Session(StrictModel):
    session_id: Identifier
    active_workflow: WorkflowId | None
    # Workflow definition version, distinct from the session state revision.
    version: int | None = Field(ge=1)
    state: SessionState
    state_version: int = Field(ge=0)
    data_json: str
    updated_at: str


class Store:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) == ":memory:":
            raise ValueError("CSOL requires a persistent SQLite file")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        # A fresh, short-lived connection per turn avoids sharing SQLite handles
        # across HTTP threads. There is still just one database and one process.
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                connection.execute("BEGIN")
                yield connection

    def get_or_create_session(self, connection: sqlite3.Connection, session_id: str) -> Session:
        connection.execute(
            """INSERT INTO sessions
               (session_id, active_workflow, version, state, state_version, data_json, updated_at)
               VALUES (?, NULL, NULL, 'IDLE', 0, '{}', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               ON CONFLICT(session_id) DO NOTHING""",
            (session_id,),
        )
        row = connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return Session.model_validate(dict(row))

    def save_session(self, connection: sqlite3.Connection, session: Session) -> Session:
        connection.execute(
            """UPDATE sessions SET active_workflow = ?, version = ?, state = ?,
               state_version = ?, data_json = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE session_id = ?""",
            (session.active_workflow, session.version, session.state, session.state_version,
             session.data_json, session.session_id),
        )
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session.session_id,)
        ).fetchone()
        return Session.model_validate(dict(row))

    def record_event(
        self, connection: sqlite3.Connection, event_type: str, before: Session, after: Session
    ) -> None:
        # Only synthetic session references, fixed event labels and states.
        # Never copy messages, message IDs, recipient data or credentials here.
        connection.execute(
            """INSERT INTO audit_events
               (session_id, event_type, from_state, to_state, state_version)
               VALUES (?, ?, ?, ?, ?)""",
            (after.session_id, event_type, before.state, after.state, after.state_version),
        )

    def obtain_transaction(
        self, connection: sqlite3.Connection, idempotency_key: str
    ) -> tuple[sqlite3.Row, bool]:
        inserted = connection.execute(
            """INSERT INTO transactions (idempotency_key, status) VALUES (?, 'PENDING')
               ON CONFLICT(idempotency_key) DO NOTHING""",
            (idempotency_key,),
        ).rowcount == 1
        row = connection.execute(
            "SELECT * FROM transactions WHERE idempotency_key = ?", (idempotency_key,),
        ).fetchone()
        return row, inserted

    def transaction_by_key(
        self, connection: sqlite3.Connection, idempotency_key: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM transactions WHERE idempotency_key = ?", (idempotency_key,),
        ).fetchone()

    def finish_transaction(
        self, connection: sqlite3.Connection, transaction_id: int, *, succeeded: bool
    ) -> None:
        connection.execute(
            "UPDATE transactions SET status = ? WHERE id = ? AND status = 'PENDING'",
            ("SUCCEEDED" if succeeded else "UNKNOWN", transaction_id),
        )
