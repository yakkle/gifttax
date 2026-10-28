import asyncio
import logging
from datetime import UTC, datetime, timedelta

from dateutil.relativedelta import relativedelta

from backend.storage.database import Database, PurgeResult

logger = logging.getLogger(__name__)

EMAIL_RETENTION = timedelta(days=90)
USAGE_RETENTION = timedelta(days=90)


def email_expiry(consented_at: datetime) -> datetime:
    return _utc(consented_at) + EMAIL_RETENTION


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Retention timestamps must include a timezone")
    return value.astimezone(UTC)


def cleanup_expired_data(database: Database, *, now: datetime | None = None) -> PurgeResult:
    current = _utc(now) if now is not None else datetime.now(UTC)
    return database.purge_expired(
        now=int(current.timestamp()),
        feedback_before=int((current - relativedelta(years=1)).timestamp()),
        usage_before=int((current - USAGE_RETENTION).timestamp()),
    )


async def maintain_storage(
    database: Database,
    stop: asyncio.Event,
    *,
    interval_seconds: float,
    ready: asyncio.Event | None = None,
) -> None:
    """Initialize and clean at startup, then retry every interval after any failure."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(database.initialize)
            await asyncio.to_thread(cleanup_expired_data, database)
        except Exception:
            logger.exception("Feedback storage maintenance failed")
        finally:
            if ready is not None:
                ready.set()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
