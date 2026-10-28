import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import OperationalError

from backend.storage.database import Database, migration_config
from backend.storage.models import (
    AdminAccount,
    AdminChallenge,
    AdminCredential,
    AdminOneTimeToken,
    AdminSession,
    Base,
    DailyUsageCount,
    Feedback,
    FeedbackContact,
    UsageEvent,
)


@pytest.fixture
def populated_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "populated.sqlite3")
    database.initialize()
    with database.session(write=True) as session:
        session.add_all(
            [
                Feedback(
                    id="feedback-id",
                    satisfaction="satisfied",
                    category="review",
                    message="저장된 의견",
                    source="result",
                    status="resolved",
                    created_at=100,
                    contact=FeedbackContact(
                        email="reader@example.com", consented_at=100, expires_at=200
                    ),
                ),
                UsageEvent(
                    event_id="event-id",
                    event_type="support_click",
                    visitor_id="visitor-id",
                    source="feedback",
                    target="fairy",
                    occurred_at=100,
                ),
                DailyUsageCount(day="2026-10-20", event_type="support_click", event_count=7),
                AdminAccount(
                    id=1,
                    user_handle=b"user-handle",
                    created_at=100,
                    credentials=[
                        AdminCredential(
                            credential_id=b"credential-id",
                            public_key=b"public-key",
                            sign_count=5,
                            label="패스키",
                            created_at=100,
                            last_used_at=150,
                        )
                    ],
                    sessions=[
                        AdminSession(session_id="session-id", created_at=100, expires_at=200)
                    ],
                ),
                AdminOneTimeToken(
                    token_hash="token-hash", purpose="login", created_at=100, expires_at=200
                ),
                AdminChallenge(
                    challenge_id="challenge-id",
                    challenge=b"challenge",
                    purpose="authentication",
                    binding_hash="binding-hash",
                    created_at=100,
                    expires_at=200,
                ),
            ]
        )
    return database


def snapshot_rows(database: Database) -> dict[str, list[tuple]]:
    with database.session() as session:
        return {
            name: [
                tuple(row)
                for row in session.execute(select(table).order_by(*table.primary_key.columns))
            ]
            for name, table in Base.metadata.tables.items()
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


def test_reinitialization_preserves_all_rows_and_constraints(populated_database: Database) -> None:
    before_rows = snapshot_rows(populated_database)
    before_schema = snapshot_schema(populated_database)
    populated_database.initialize()
    populated_database.initialize()
    assert snapshot_rows(populated_database) == before_rows
    assert snapshot_schema(populated_database) == before_schema
    with populated_database.session() as session:
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
    assert_no_schema_drift(populated_database)


def test_failed_schema_change_rolls_back_data_and_revision(
    populated_database: Database, tmp_path: Path
) -> None:
    before_rows, before_schema = (
        snapshot_rows(populated_database),
        snapshot_schema(populated_database),
    )
    scripts = tmp_path / "migration-scripts"
    config = migration_config()
    shutil.copytree(
        config.get_main_option("script_location"),
        scripts,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (scripts / "versions" / "test_next.py").write_text(
        "import sqlalchemy as sa\nfrom alembic import op\n"
        'revision = "test_next"\ndown_revision = "0001"\n'
        "def upgrade():\n"
        '    op.add_column("feedback", sa.Column("temporary_value", sa.Text()))\n'
        '    raise RuntimeError("simulated upgrade failure")\n'
        "def downgrade():\n    pass\n"
    )
    config.set_main_option("script_location", str(scripts).replace("%", "%%"))
    with pytest.raises(RuntimeError, match="simulated upgrade failure"):
        with populated_database.migration_connection() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    assert snapshot_rows(populated_database) == before_rows
    assert snapshot_schema(populated_database) == before_schema
    with populated_database.session() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    assert_no_schema_drift(populated_database)


def test_new_database_matches_orm_metadata(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    database.initialize()
    assert_no_schema_drift(database)


def test_reading_revision_does_not_modify_database(populated_database: Database) -> None:
    before_rows, before_schema = (
        snapshot_rows(populated_database),
        snapshot_schema(populated_database),
    )
    with populated_database.migration_connection() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.current(config)
    assert snapshot_rows(populated_database) == before_rows
    assert snapshot_schema(populated_database) == before_schema


@pytest.mark.parametrize("conflict", ["table", "view", "index"])
def test_conflicting_existing_schema_is_not_overwritten(tmp_path: Path, conflict: str) -> None:
    database = Database(tmp_path / "conflict.sqlite3")
    with sqlite3.connect(database.path) as connection:
        connection.execute("CREATE TABLE another_service (message TEXT)")
        connection.execute("INSERT INTO another_service VALUES ('preserve this')")
        statements = {
            "table": "CREATE TABLE feedback (message TEXT)",
            "view": "CREATE VIEW feedback AS SELECT message FROM another_service",
            "index": "CREATE INDEX feedback_created_at ON another_service(message)",
        }
        connection.execute(statements[conflict])
    before_schema = snapshot_schema(database)
    with pytest.raises(OperationalError):
        database.initialize()
    assert snapshot_schema(database) == before_schema
    with sqlite3.connect(database.path) as connection:
        assert (
            connection.execute("SELECT message FROM another_service").fetchone()[0]
            == "preserve this"
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
            ).fetchone()
            is None
        )


def test_unknown_revision_is_rejected_without_changes(populated_database: Database) -> None:
    with populated_database.session(write=True) as session:
        session.execute(text("UPDATE alembic_version SET version_num = 'unknown_future_revision'"))
    before = snapshot_rows(populated_database)
    with pytest.raises(CommandError, match="Can't locate revision"):
        populated_database.initialize()
    assert snapshot_rows(populated_database) == before
    with populated_database.session() as session:
        assert (
            session.scalar(text("SELECT version_num FROM alembic_version"))
            == "unknown_future_revision"
        )


def test_unrelated_existing_tables_are_preserved(tmp_path: Path) -> None:
    database = Database(tmp_path / "existing.sqlite3")
    with sqlite3.connect(database.path) as connection:
        connection.execute("CREATE TABLE another_service (message TEXT)")
        connection.execute("INSERT INTO another_service VALUES ('preserve this')")
    database.initialize()
    with sqlite3.connect(database.path) as connection:
        assert (
            connection.execute("SELECT message FROM another_service").fetchone()[0]
            == "preserve this"
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"


def test_failed_upgrade_rolls_back_revision_marker(tmp_path: Path) -> None:
    database = Database(tmp_path / "revision-failure.sqlite3")

    def failing_version_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO alembic_version"):
            raise RuntimeError("simulated revision failure")

    event.listen(database.engine, "before_cursor_execute", failing_version_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated revision failure"):
            database.initialize()
    finally:
        event.remove(database.engine, "before_cursor_execute", failing_version_insert)
    with sqlite3.connect(database.path) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            == []
        )
    database.initialize()
    assert_no_schema_drift(database)


@pytest.mark.parametrize("existing_data", [False, True])
def test_alembic_downgrade_and_upgrade_on_disposable_database(
    tmp_path: Path, populated_database: Database, existing_data: bool
) -> None:
    database = populated_database if existing_data else Database(tmp_path / "disposable.sqlite3")
    database.initialize()
    with database.migration_connection() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    database.initialize()
    assert_no_schema_drift(database)


def test_orm_relationships_and_cascade(populated_database: Database) -> None:
    with populated_database.session(write=True) as session:
        feedback = session.get(Feedback, "feedback-id")
        feedback.message = "ORM으로 수정한 의견"
        feedback.contact.email = "updated@example.com"
    with populated_database.session() as session:
        assert session.get(Feedback, "feedback-id").message == "ORM으로 수정한 의견"
        assert session.get(FeedbackContact, "feedback-id").email == "updated@example.com"
    with populated_database.session(write=True) as session:
        session.delete(session.get(Feedback, "feedback-id"))
    with populated_database.session() as session:
        assert session.get(FeedbackContact, "feedback-id") is None
