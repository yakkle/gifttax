import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from backend.storage.migrations import MIGRATIONS, SCHEMA_VERSION

SQLITE_TIMEOUT_SECONDS = 5


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


class UnsupportedSchemaVersionError(RuntimeError):
    """The database was created by a newer application; do not downgrade it."""


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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, timeout=SQLITE_TIMEOUT_SECONDS, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Each operation owns a connection; writers wait up to five seconds."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            _enable_wal(connection)
        finally:
            connection.close()

        with self.transaction(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"Database schema {version} exceeds supported version {SCHEMA_VERSION}"
                )
            for target_version in range(version + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[target_version]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {target_version}")

    def purge_expired(
        self, *, now: int, feedback_before: int, usage_before: int
    ) -> PurgeResult:
        """Apply service-provided cutoffs atomically, retaining daily aggregates."""
        with self.transaction(write=True) as connection:
            contacts = connection.execute(
                "DELETE FROM feedback_contacts WHERE expires_at <= ?", (now,)
            ).rowcount
            feedback = connection.execute(
                "DELETE FROM feedback WHERE created_at <= ?", (feedback_before,)
            ).rowcount
            usage_events = connection.execute(
                "DELETE FROM usage_events WHERE occurred_at <= ?", (usage_before,)
            ).rowcount
            sessions = connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?", (now,)
            ).rowcount
            tokens = connection.execute(
                "DELETE FROM admin_one_time_tokens WHERE expires_at <= ?", (now,)
            ).rowcount
            challenges = connection.execute(
                "DELETE FROM admin_challenges WHERE expires_at <= ?", (now,)
            ).rowcount
        return PurgeResult(contacts, feedback, usage_events, sessions, tokens, challenges)
