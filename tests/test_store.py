import sqlite3

import pytest

from csol.store import Store


def test_in_memory_database_is_rejected():
    with pytest.raises(ValueError, match="persistent SQLite file"):
        Store(":memory:")


def test_persistent_schema_has_required_tables_and_session_fields(tmp_path):
    path = tmp_path / "nested" / "state.sqlite3"
    store = Store(path)
    assert path.is_file()
    with store.transaction() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert tables == {"sessions", "transactions", "processed_messages", "feedback", "audit_events"}
        assert {row[1] for row in connection.execute("PRAGMA table_info(sessions)")} == {
            "session_id", "active_workflow", "version", "state", "state_version", "data_json", "updated_at",
        }
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        session = store.get_or_create_session(connection, "demo-schema")
        assert (session.state, session.state_version, session.version, session.data_json) == ("IDLE", 0, None, "{}")
        assert session.updated_at.endswith("Z")
    # Schema initialization is repeatable and preserves the database contents.
    restarted = Store(path)
    with restarted.transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_required_unique_keys_are_enforced_by_sqlite(tmp_path):
    store = Store(tmp_path / "schema.sqlite3")
    with store.transaction() as connection:
        store.get_or_create_session(connection, "demo-one")
        store.get_or_create_session(connection, "demo-two")
        # Schema-only fixtures: no transaction backend exists or is called.
        connection.execute("INSERT INTO transactions (idempotency_key, status) VALUES ('schema-only', 'PENDING')")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute("INSERT INTO transactions (idempotency_key, status) VALUES ('schema-only', 'PENDING')")
        connection.execute("INSERT INTO processed_messages VALUES ('demo-one', 'message-1', '{}')")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute("INSERT INTO processed_messages VALUES ('demo-one', 'message-1', '{}')")
        connection.execute("INSERT INTO processed_messages VALUES ('demo-two', 'message-1', '{}')")
        connection.execute("INSERT INTO processed_messages VALUES ('demo-one', 'message-2', '{}')")
        assert connection.execute("SELECT COUNT(*) FROM processed_messages").fetchone()[0] == 3
