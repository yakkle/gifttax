from alembic import context
from sqlalchemy import URL, Connection

from backend.settings import Settings
from backend.storage.migration_support import is_legacy_schema
from backend.storage.models import Base

config = context.config


def run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        if not context.get_context().get_current_heads():
            is_legacy_schema(connection)
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=URL.create("sqlite+pysqlite", database=str(Settings().database_path)),
        target_metadata=Base.metadata,
        literal_binds=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif (connection := config.attributes.get("connection")) is not None:
    run_with_connection(connection)
else:
    from backend.storage.database import Database

    database = Database(Settings().database_path)
    try:
        with database.migration_connection() as connection:
            run_with_connection(connection)
    finally:
        database.dispose()
