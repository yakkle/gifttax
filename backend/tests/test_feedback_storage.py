import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.models.feedback import ClientUsageEvent, FeedbackCreate, UsageEventType
from backend.services.retention import cleanup_expired_data, email_expiry, maintain_storage
from backend.settings import Settings
from backend.storage.database import Database, UnsupportedSchemaVersionError, _enable_wal
from backend.storage.migrations import SCHEMA_VERSION

NOW = datetime(2026, 10, 19, 3, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "data" / "feedback.sqlite3")
    database.initialize()
    return database


def insert_feedback(database: Database, created_at: datetime = NOW) -> str:
    feedback_id = str(uuid4())
    with database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO feedback (id, category, message, source, created_at)
               VALUES (?, 'review', '의견입니다', 'general', ?)""",
            (feedback_id, int(created_at.timestamp())),
        )
    return feedback_id


def add_contact(database: Database, feedback_id: str, consented_at: datetime) -> None:
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO feedback_contacts VALUES (?, ?, ?, ?)",
            (
                feedback_id,
                "reader@example.com",
                int(consented_at.timestamp()),
                int(email_expiry(consented_at).timestamp()),
            ),
        )


def row_count(database: Database, table: str) -> int:
    with database.transaction() as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_initialize_persists_data_and_is_idempotent(database: Database) -> None:
    feedback_id = insert_feedback(database)
    reopened = Database(database.path)
    reopened.initialize()
    with reopened.transaction() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        row = connection.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        assert row["message"] == "의견입니다"
        assert row["status"] == "new"


def test_migration_failure_rolls_back_schema_and_version(tmp_path: Path) -> None:
    database = Database(tmp_path / "feedback.sqlite3")
    with (
        patch.dict(
            "backend.storage.database.MIGRATIONS",
            {1: ("CREATE TABLE partial (id INTEGER)", "NOT VALID SQL")},
        ),
        pytest.raises(sqlite3.OperationalError),
    ):
        database.initialize()
    with database.transaction() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'partial'"
        ).fetchone() is None
    database.initialize()
    assert row_count(database, "feedback") == 0


def test_newer_schema_is_rejected_without_losing_data(database: Database) -> None:
    insert_feedback(database)
    with database.transaction(write=True) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(UnsupportedSchemaVersionError):
        database.initialize()
    assert row_count(database, "feedback") == 1


def test_concurrent_initialization_is_safe(tmp_path: Path) -> None:
    path = tmp_path / "feedback.sqlite3"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: Database(path).initialize(), range(8)))
    assert row_count(Database(path), "feedback") == 0


def test_wal_setup_retries_a_temporary_lock(database: Database) -> None:
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    with database.transaction() as connection:
        wrapped = MagicMock(wraps=connection)
        wrapped.execute.side_effect = [error, connection.execute("PRAGMA journal_mode")]
        _enable_wal(wrapped)


def test_wal_setup_does_not_hide_permanent_errors() -> None:
    connection = MagicMock()
    connection.execute.side_effect = sqlite3.OperationalError("disk I/O error")
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        _enable_wal(connection)


def test_concurrent_writes_keep_events_and_counts_consistent(database: Database) -> None:
    def record_event(_: int) -> None:
        with database.transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO usage_events (event_id, event_type, occurred_at) VALUES (?, ?, ?)",
                (str(uuid4()), "page_view", int(NOW.timestamp())),
            )
            connection.execute(
                """INSERT INTO daily_usage_counts VALUES ('2026-10-19', 'page_view', 1)
                   ON CONFLICT (day, event_type)
                   DO UPDATE SET event_count = event_count + 1"""
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(record_event, range(40)))
    assert row_count(database, "usage_events") == 40
    with database.transaction() as connection:
        assert connection.execute("SELECT event_count FROM daily_usage_counts").fetchone()[0] == 40


def test_transaction_rolls_back_related_writes(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError), database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO feedback (id, satisfaction, category, source, created_at)
               VALUES ('first', 'satisfied', 'review', 'result', ?)""",
            (int(NOW.timestamp()),),
        )
        connection.execute(
            "INSERT INTO feedback_contacts VALUES ('missing', 'reader@example.com', 1, 2)"
        )
    assert row_count(database, "feedback") == 0


def test_feedback_submission_id_is_unique(database: Database) -> None:
    feedback_id = insert_feedback(database)
    with pytest.raises(sqlite3.IntegrityError), database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO feedback (id, satisfaction, category, source, created_at)
               VALUES (?, 'satisfied', 'review', 'result', ?)""",
            (feedback_id, int(NOW.timestamp())),
        )
    assert row_count(database, "feedback") == 1


def test_empty_feedback_is_rejected_by_storage(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError), database.transaction(write=True) as connection:
        connection.execute(
            """INSERT INTO feedback (id, category, message, source, created_at)
               VALUES ('empty', 'review', '   ', 'general', 0)"""
        )


def test_deleting_feedback_cascades_only_its_contact(database: Database) -> None:
    first, second = insert_feedback(database), insert_feedback(database)
    add_contact(database, first, NOW)
    add_contact(database, second, NOW)
    with database.transaction(write=True) as connection:
        connection.execute("DELETE FROM feedback WHERE id = ?", (first,))
    assert row_count(database, "feedback_contacts") == 1
    with database.transaction() as connection:
        assert connection.execute("SELECT feedback_id FROM feedback_contacts").fetchone()[0] == second


def test_retention_removes_expired_contacts_but_keeps_feedback(database: Database) -> None:
    expired, current = insert_feedback(database), insert_feedback(database)
    add_contact(database, expired, NOW - timedelta(days=90))
    add_contact(database, current, NOW - timedelta(days=90) + timedelta(seconds=1))
    result = cleanup_expired_data(database, now=NOW)
    assert result.contacts == 1
    assert result.feedback == 0
    assert row_count(database, "feedback") == 2
    with database.transaction() as connection:
        assert connection.execute("SELECT feedback_id FROM feedback_contacts").fetchone()[0] == current


def test_retention_uses_calendar_year_and_preserves_recent_feedback(database: Database) -> None:
    now = datetime(2025, 2, 28, tzinfo=UTC)
    insert_feedback(database, datetime(2024, 2, 28, tzinfo=UTC))
    leap_day = insert_feedback(database, datetime(2024, 2, 29, tzinfo=UTC))
    add_contact(database, leap_day, datetime(2024, 2, 29, tzinfo=UTC))
    result = cleanup_expired_data(database, now=now)
    assert result.feedback == 1
    assert result.contacts == 1
    assert row_count(database, "feedback") == 1


def test_retention_deletes_raw_events_and_preserves_daily_totals(database: Database) -> None:
    cutoff = int((NOW - timedelta(days=90)).timestamp())
    with database.transaction(write=True) as connection:
        for occurred_at in (cutoff, cutoff + 1):
            connection.execute(
                "INSERT INTO usage_events (event_id, event_type, visitor_id, occurred_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), "page_view", str(uuid4()), occurred_at),
            )
        connection.execute("INSERT INTO daily_usage_counts VALUES ('2026-07-21', 'page_view', 2)")
    result = cleanup_expired_data(database, now=NOW)
    assert result.usage_events == 1
    assert row_count(database, "usage_events") == 1
    with database.transaction() as connection:
        assert connection.execute("SELECT event_count FROM daily_usage_counts").fetchone()[0] == 2


def test_retention_cleans_expired_auth_artifacts_but_keeps_credentials(database: Database) -> None:
    now = int(NOW.timestamp())
    with database.transaction(write=True) as connection:
        connection.execute("INSERT INTO admin_account VALUES (1, ?, ?)", (b"user", now - 100))
        connection.execute(
            """INSERT INTO admin_credentials
               (credential_id, admin_id, public_key, sign_count, label, created_at)
               VALUES (?, 1, ?, 0, 'test', ?)""",
            (b"credential", b"public-key", now - 100),
        )
        for suffix, expiry in (("expired", now), ("live", now + 1)):
            connection.execute(
                "INSERT INTO admin_sessions VALUES (?, 1, ?, ?)", (suffix, now - 100, expiry)
            )
            connection.execute(
                "INSERT INTO admin_one_time_tokens VALUES (?, 'login', ?, ?)",
                (suffix, now - 100, expiry),
            )
            connection.execute(
                "INSERT INTO admin_challenges VALUES (?, ?, 'authentication', ?, ?, ?)",
                (suffix, b"challenge", "binding-hash", now - 100, expiry),
            )
    result = cleanup_expired_data(database, now=NOW)
    assert (result.sessions, result.tokens, result.challenges) == (1, 1, 1)
    assert row_count(database, "admin_credentials") == 1
    assert row_count(database, "admin_account") == 1
    assert row_count(database, "admin_sessions") == 1
    assert cleanup_expired_data(database, now=NOW).sessions == 0


def test_retention_failure_rolls_back_all_deletions(database: Database) -> None:
    feedback_id = insert_feedback(database, NOW - timedelta(days=400))
    add_contact(database, feedback_id, NOW - timedelta(days=100))
    with database.transaction(write=True) as connection:
        connection.execute(
            """CREATE TRIGGER fail_cleanup BEFORE DELETE ON feedback
               BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        cleanup_expired_data(database, now=NOW)
    assert row_count(database, "feedback") == 1
    assert row_count(database, "feedback_contacts") == 1


def test_retention_requires_aware_timestamps(database: Database) -> None:
    with pytest.raises(ValueError, match="timezone"):
        cleanup_expired_data(database, now=datetime(2026, 10, 19))
    with pytest.raises(ValueError, match="timezone"):
        email_expiry(datetime(2026, 10, 19))


def test_settings_use_environment_and_reject_relative_paths(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "environment.sqlite3"
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(path))
    assert Settings().database_path == path
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", "relative.sqlite3")
    with pytest.raises(ValidationError):
        Settings()
    with pytest.raises(ValidationError):
        Settings(database_path=path, retention_interval_seconds=0)


def test_feedback_contract_limits_fields_and_normalizes_text() -> None:
    feedback = FeedbackCreate(submission_id=uuid4(), message="  개선해 주세요  ")
    assert feedback.message == "개선해 주세요"
    assert feedback.category == "review"
    with pytest.raises(ValidationError):
        FeedbackCreate(submission_id=uuid4(), message="가" * 2001)
    with pytest.raises(ValidationError):
        FeedbackCreate(submission_id=uuid4(), gift_amount=10000)


def test_clients_cannot_report_server_calculation_events() -> None:
    with pytest.raises(ValidationError):
        ClientUsageEvent(event_id=uuid4(), event_type=UsageEventType.CALCULATION_SUCCESS)
    assert ClientUsageEvent(
        event_id=uuid4(), event_type="support_click", source="feedback", target="fairy"
    ).target == "fairy"


def test_startup_initializes_and_cleans_persisted_database(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "feedback.sqlite3")
    database.initialize()
    insert_feedback(database, datetime(2000, 1, 1, tzinfo=UTC))
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(database.path))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert app.state.database.path == database.path
        assert row_count(database, "feedback") == 0


def test_storage_outage_does_not_block_existing_routes(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(tmp_path / "feedback.sqlite3"))
    with patch.object(Database, "initialize", side_effect=sqlite3.OperationalError("unavailable")):
        with TestClient(app) as client:
            assert client.get("/api/health").json() == {"status": "ok"}
            assert client.get("/").status_code == 200
    assert "Feedback storage maintenance failed" in caplog.text


def test_maintenance_retries_after_failure_and_stops_promptly(database: Database) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        stop, ready, retried = asyncio.Event(), asyncio.Event(), asyncio.Event()
        initialize = database.initialize
        attempts = 0

        def flaky_initialize() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("temporary failure")
            initialize()
            loop.call_soon_threadsafe(retried.set)

        with patch.object(database, "initialize", side_effect=flaky_initialize):
            task = asyncio.create_task(
                maintain_storage(database, stop, interval_seconds=0.01, ready=ready)
            )
            try:
                await asyncio.wait_for(ready.wait(), timeout=2)
                await asyncio.wait_for(retried.wait(), timeout=2)
            finally:
                stop.set()
                await asyncio.wait_for(task, timeout=2)
        assert attempts >= 2

    asyncio.run(scenario())
