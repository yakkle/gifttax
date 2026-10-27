"""Atomic event/aggregate writes and read-only ORM reporting queries."""

from dataclasses import dataclass

from sqlalchemy import Integer, cast, func, select

from backend.storage.database import Database
from backend.storage.models import DailyUsageCount, UsageEvent


@dataclass(frozen=True)
class UsageRows:
    counts: list[tuple[str, str, int]]
    unique_visitors: list[tuple[str, int]]
    daily_visitors: list[tuple[int, str, int]]


class UsageRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        *,
        event_id: str,
        event_type: str,
        visitor_id: str,
        occurred_at: int,
        day: str,
        source: str | None = None,
        target: str | None = None,
    ) -> None:
        with self.database.session(write=True) as session:
            if session.get(UsageEvent, event_id) is not None:
                return
            session.add(
                UsageEvent(
                    event_id=event_id,
                    event_type=event_type,
                    visitor_id=visitor_id,
                    occurred_at=occurred_at,
                    source=source,
                    target=target,
                )
            )
            daily = session.get(DailyUsageCount, (day, event_type))
            if daily is None:
                session.add(DailyUsageCount(day=day, event_type=event_type, event_count=1))
            else:
                daily.event_count += 1

    def summary(
        self,
        *,
        start: int,
        end: int,
        first_day: str,
        last_day: str,
        utc_offset: int,
    ) -> UsageRows:
        with self.database.session() as session:
            counts = session.execute(
                select(
                    DailyUsageCount.day,
                    DailyUsageCount.event_type,
                    DailyUsageCount.event_count,
                ).where(DailyUsageCount.day >= first_day, DailyUsageCount.day <= last_day)
            ).all()
            visitors = select(
                UsageEvent.event_type, func.count(func.distinct(UsageEvent.visitor_id))
            ).where(
                UsageEvent.occurred_at >= start,
                UsageEvent.occurred_at < end,
                UsageEvent.visitor_id.is_not(None),
                UsageEvent.event_type.in_(("page_view", "calculation_success")),
            )
            unique = session.execute(visitors.group_by(UsageEvent.event_type)).all()
            day_bucket = cast((UsageEvent.occurred_at + utc_offset) / 86400, Integer)
            daily = session.execute(
                visitors.add_columns(day_bucket).group_by(
                    day_bucket,
                    UsageEvent.event_type,
                )
            ).all()
            return UsageRows(
                counts=[tuple(row) for row in counts],
                unique_visitors=[tuple(row) for row in unique],
                daily_visitors=[(bucket, event_type, count) for event_type, count, bucket in daily],
            )
