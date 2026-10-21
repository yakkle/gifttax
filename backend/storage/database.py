import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic, sleep

from alembic import command
from sqlalchemy import URL, Connection, create_engine, delete, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from backend.storage.migration_support import (
    UnsupportedSchemaVersionError as UnsupportedSchemaVersionError,
)
from backend.storage.migration_support import migration_config
from backend.storage.models import (
    AdminChallenge,
    AdminOneTimeToken,
    AdminSession,
    Feedback,
    FeedbackContact,
    UsageEvent,
)

SQLITE_TIMEOUT_SECONDS = 5
_MIGRATION_LOCK = RLock()


def _configure_sqlite(connection: sqlite3.Connection, _: ConnectionPoolEntry) -> None:
    # SQLAlchemy owns BEGIN, including transactional DDL and immediate writes.
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys = ON")


def _begin_sqlite(connection: Connection) -> None:
    immediate = connection.get_execution_options().get("sqlite_write", False)
    connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")


def _enable_wal(connection: sqlite3.Connection) -> None:
    # SQLite can bypass its busy handler during concurrent journal-mode changes.
    deadline = monotonic() + SQLITE_TIMEOUT_SECONDS
    while True:
        try:
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if mode != "wal":
                raise sqlite3.OperationalError("The feedback database requires WAL journal mode")
            return
        except sqlite3.OperationalError as error:
            code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or monotonic() >= deadline:
                raise
            sleep(0.01)


@dataclass(frozen=True)
class PurgeResult:
    contacts: int
    feedback: int
    usage_events: int
    sessions: int
    tokens: int
    challenges: int


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(path)),
            connect_args={"timeout": SQLITE_TIMEOUT_SECONDS, "check_same_thread": False},
            poolclass=NullPool,
            hide_parameters=True,
        )
        event.listen(self.engine, "connect", _configure_sqlite)
        event.listen(self.engine, "begin", _begin_sqlite)

    @contextmanager
    def session(self, *, write: bool = False) -> Iterator[Session]:
        """Own one ORM session/transaction; roll back automatically on failure."""
        with Session(self.engine) as session, session.begin():
            session.connection(execution_options={"sqlite_write": write})
            yield session

    @contextmanager
    def migration_connection(self) -> Iterator[Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = self.engine.raw_connection()
        try:
            _enable_wal(raw.driver_connection)
        finally:
            raw.close()
        with self.engine.connect().execution_options(sqlite_write=True) as connection:
            with connection.begin():
                yield connection

    def initialize(self) -> None:
        # Alembic's command context is process-global; serialize in-process runs.
        with _MIGRATION_LOCK, self.migration_connection() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def dispose(self) -> None:
        self.engine.dispose()

    def purge_expired(self, *, now: int, feedback_before: int, usage_before: int) -> PurgeResult:
        """Apply service-provided cutoffs atomically, retaining daily aggregates."""
        statements = (
            delete(FeedbackContact).where(FeedbackContact.expires_at <= now),
            delete(Feedback).where(Feedback.created_at <= feedback_before),
            delete(UsageEvent).where(UsageEvent.occurred_at <= usage_before),
            delete(AdminSession).where(AdminSession.expires_at <= now),
            delete(AdminOneTimeToken).where(AdminOneTimeToken.expires_at <= now),
            delete(AdminChallenge).where(AdminChallenge.expires_at <= now),
        )
        with self.session(write=True) as session:
            counts = [
                session.execute(
                    statement, execution_options={"synchronize_session": False}
                ).rowcount
                for statement in statements
            ]
        return PurgeResult(*counts)
