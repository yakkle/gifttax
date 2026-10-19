"""Alembic configuration and a conservative bridge from the original SQLite schema."""

import re
from pathlib import Path

from alembic.config import Config
from sqlalchemy import Connection

from backend.storage.migrations import MIGRATIONS, SCHEMA_VERSION


class UnsupportedSchemaVersionError(RuntimeError):
    """The database is newer than, or incompatible with, this application."""


def migration_config() -> Config:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parent / "alembic").replace("%", "%%")
    )
    return config


def _normalize_ddl(statement: str) -> str:
    return " ".join(statement.split())


def is_legacy_schema(connection: Connection) -> bool:
    """Validate the immutable v1 layout without writing or assigning a revision."""
    version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
    if version > SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(f"Unsupported legacy schema version: {version}")

    actual = {
        name: _normalize_ddl(ddl)
        for name, ddl in connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger', 'view') AND name NOT LIKE 'sqlite_%' "
            "AND name != 'alembic_version' AND sql IS NOT NULL"
        )
    }
    if version == 0 and not actual:
        return False

    expected = {}
    for statement in MIGRATIONS[SCHEMA_VERSION]:
        match = re.match(r"\s*CREATE (?:TABLE|INDEX) (\w+)", statement)
        if match is not None:
            expected[match.group(1)] = _normalize_ddl(statement)
    if version != SCHEMA_VERSION or actual != expected:
        raise UnsupportedSchemaVersionError("Legacy database does not match the known schema")

    return True
