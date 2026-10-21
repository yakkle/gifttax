import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text

from backend.storage.database import Database
from backend.storage.migration_support import UnsupportedSchemaVersionError, migration_config
from backend.storage.migrations import MIGRATIONS, SCHEMA_VERSION
from backend.storage.models import AdminAccount, AdminCredential, Base, Feedback, FeedbackContact


@pytest.fixture
def legacy_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in MIGRATIONS[SCHEMA_VERSION]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute(
            """INSERT INTO feedback (id, satisfaction, category, message, source, status, created_at)
               VALUES ('feedback-id', 'satisfied', 'review', '기존 의견', 'result', 'resolved', 100)"""
        )
        connection.execute(
            "INSERT INTO feedback_contacts VALUES ('feedback-id', 'reader@example.com', 100, 200)"
        )
        connection.execute(
            "INSERT INTO usage_events VALUES ('event-id', 'support_click', 'visitor-id', 'feedback', 'fairy', 100)"
        )
        connection.execute(
            "INSERT INTO daily_usage_counts VALUES ('2026-10-20', 'support_click', 7)"
        )
        connection.execute("INSERT INTO admin_account VALUES (1, ?, 100)", (b"user-handle",))
        connection.execute(
            "INSERT INTO admin_credentials VALUES (?, 1, ?, 5, '[]', '기존 패스키', 100, 150)",
            (b"credential-id", b"public-key"),
        )
        connection.execute("INSERT INTO admin_sessions VALUES ('session-id', 1, 100, 200)")
        connection.execute(
            "INSERT INTO admin_one_time_tokens VALUES ('token-hash', 'login', 100, 200)"
        )
        connection.execute(
            "INSERT INTO admin_challenges VALUES ('challenge-id', ?, 'authentication', 'binding-hash', 100, 200)",
            (b"challenge",),
        )
    return database


def snapshot_rows(database: Database) -> dict[str, list[tuple]]:
    with sqlite3.connect(database.path) as connection:
        return {
            name: connection.execute(f'SELECT * FROM "{name}"').fetchall()
            for name in Base.metadata.tables
        }


def snapshot_schema(database: Database) -> list[tuple]:
    with sqlite3.connect(database.path) as connection:
        return connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "AND name != 'alembic_version' ORDER BY name"
        ).fetchall()


def assert_no_schema_drift(database: Database) -> None:
    with database.migration_connection() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.check(config)


def test_adopt_legacy_database_preserves_all_rows_and_constraints(
    legacy_database: Database,
) -> None:
    before_rows = snapshot_rows(legacy_database)
    before_schema = snapshot_schema(legacy_database)
    legacy_database.initialize()
    legacy_database.initialize()
    assert snapshot_rows(legacy_database) == before_rows
    after_schema = snapshot_schema(legacy_database)
    rewritten = {"feedback_contacts", "feedback_contacts_expiry"}
    assert [row for row in after_schema if row[0] not in rewritten] == [
        row for row in before_schema if row[0] not in rewritten
    ]
    with legacy_database.session() as session:
        head = ScriptDirectory.from_config(migration_config()).get_current_head()
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == head
        assert session.get(Feedback, "feedback-id").contact.email == "reader@example.com"
        assert session.get(AdminAccount, 1).credentials[0].public_key == b"public-key"
        assert session.get(AdminCredential, b"credential-id").sign_count == 5
        checks = inspect(session.connection()).get_check_constraints("feedback_contacts")
        assert {check["sqltext"] for check in checks} == {
            "length(email) BETWEEN 1 AND 254",
            "expires_at > consented_at",
        }
    assert_no_schema_drift(legacy_database)


def test_failed_contact_normalization_rolls_back_legacy_adoption(legacy_database: Database) -> None:
    before_rows, before_schema = snapshot_rows(legacy_database), snapshot_schema(legacy_database)
    original = Operations.batch_alter_table

    @contextmanager
    def failing_batch(operations, *args, **kwargs):
        with original(operations, *args, **kwargs) as batch:
            yield batch
        raise RuntimeError("simulated normalization failure")

    with (
        patch.object(Operations, "batch_alter_table", failing_batch),
        pytest.raises(RuntimeError, match="simulated normalization failure"),
    ):
        legacy_database.initialize()
    assert snapshot_rows(legacy_database) == before_rows
    assert snapshot_schema(legacy_database) == before_schema
    with sqlite3.connect(legacy_database.path) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
            ).fetchone()
            is None
        )
    legacy_database.initialize()
    assert_no_schema_drift(legacy_database)


def test_new_database_matches_orm_metadata(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    database.initialize()
    assert_no_schema_drift(database)


def test_reading_legacy_revision_does_not_adopt_database(legacy_database: Database) -> None:
    before_rows, before_schema = snapshot_rows(legacy_database), snapshot_schema(legacy_database)
    with legacy_database.migration_connection() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.current(config)
    assert snapshot_rows(legacy_database) == before_rows
    assert snapshot_schema(legacy_database) == before_schema
    with sqlite3.connect(legacy_database.path) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
            ).fetchone()
            is None
        )


@pytest.mark.parametrize("change", ["column", "trigger", "view"])
def test_legacy_schema_changes_are_not_silently_stamped(
    legacy_database: Database, change: str
) -> None:
    with sqlite3.connect(legacy_database.path) as connection:
        statements = {
            "column": "ALTER TABLE feedback ADD COLUMN unexpected TEXT",
            "trigger": "CREATE TRIGGER custom_contact AFTER INSERT ON feedback_contacts BEGIN SELECT 1; END",
            "view": "CREATE VIEW feedback_summary AS SELECT id FROM feedback",
        }
        connection.execute(statements[change])
    before = snapshot_rows(legacy_database)
    with pytest.raises(UnsupportedSchemaVersionError, match="known schema"):
        legacy_database.initialize()
    assert snapshot_rows(legacy_database) == before
    with sqlite3.connect(legacy_database.path) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
            ).fetchone()
            is None
        )


def test_newer_legacy_version_is_rejected_without_changes(legacy_database: Database) -> None:
    before = snapshot_rows(legacy_database)
    with sqlite3.connect(legacy_database.path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(UnsupportedSchemaVersionError, match="Unsupported legacy"):
        legacy_database.initialize()
    assert snapshot_rows(legacy_database) == before


def test_unversioned_existing_tables_are_not_adopted(tmp_path: Path) -> None:
    database = Database(tmp_path / "unrecognized.sqlite3")
    with sqlite3.connect(database.path) as connection:
        connection.execute("CREATE TABLE another_service (message TEXT)")
        connection.execute("INSERT INTO another_service VALUES ('preserve this')")
    with pytest.raises(UnsupportedSchemaVersionError):
        database.initialize()
    with sqlite3.connect(database.path) as connection:
        assert (
            connection.execute("SELECT message FROM another_service").fetchone()[0]
            == "preserve this"
        )


def test_failed_legacy_adoption_rolls_back_revision_marker(legacy_database: Database) -> None:
    before = snapshot_rows(legacy_database)

    def failing_version_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO alembic_version"):
            raise RuntimeError("simulated adoption failure")

    event.listen(legacy_database.engine, "before_cursor_execute", failing_version_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated adoption failure"):
            legacy_database.initialize()
    finally:
        event.remove(legacy_database.engine, "before_cursor_execute", failing_version_insert)
    assert snapshot_rows(legacy_database) == before
    with sqlite3.connect(legacy_database.path) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
            ).fetchone()
            is None
        )
    legacy_database.initialize()
    assert_no_schema_drift(legacy_database)


@pytest.mark.parametrize("legacy", [False, True])
def test_alembic_downgrade_and_upgrade_on_disposable_database(
    tmp_path: Path, legacy_database: Database, legacy: bool
) -> None:
    database = legacy_database if legacy else Database(tmp_path / "disposable.sqlite3")
    database.initialize()
    with database.migration_connection() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    database.initialize()
    assert_no_schema_drift(database)


def test_adopted_database_supports_orm_relationships_and_cascade(legacy_database: Database) -> None:
    legacy_database.initialize()
    with legacy_database.session(write=True) as session:
        feedback = session.get(Feedback, "feedback-id")
        feedback.message = "ORM으로 수정한 의견"
        feedback.contact.email = "updated@example.com"
    with legacy_database.session() as session:
        assert session.get(Feedback, "feedback-id").message == "ORM으로 수정한 의견"
        assert session.get(FeedbackContact, "feedback-id").email == "updated@example.com"
    with legacy_database.session(write=True) as session:
        session.delete(session.get(Feedback, "feedback-id"))
    with legacy_database.session() as session:
        assert session.get(FeedbackContact, "feedback-id") is None
