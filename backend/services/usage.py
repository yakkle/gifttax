"""Anonymous usage policy, event validation, and Korea-calendar reporting."""

import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from datetime import time as day_time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from backend.schemas.usage import (
    ClientUsageEvent,
    DailyUsage,
    UsageCounts,
    UsageEventType,
    UsageSummary,
)
from backend.storage.usage import UsageRepository

KOREA = ZoneInfo("Asia/Seoul")
VISITOR_SECONDS = 90 * 24 * 60 * 60
EVENT_FIELDS = {
    UsageEventType.PAGE_VIEW: "page_views",
    UsageEventType.CALCULATION_SUCCESS: "calculation_successes",
    UsageEventType.CALCULATION_FAILURE: "calculation_failures",
    UsageEventType.GIFT_PDF_DOWNLOAD: "gift_pdf_downloads",
    UsageEventType.RATE_PDF_DOWNLOAD: "rate_pdf_downloads",
    UsageEventType.FEEDBACK_SUBMITTED: "feedback_submissions",
    UsageEventType.SUPPORT_CLICK: "support_clicks",
}
VISITOR_FIELDS = {"page_view": "visitors", "calculation_success": "calculation_users"}


class UsageError(Exception):
    pass


def browser_id(value: str | None) -> tuple[str, bool]:
    try:
        parsed = UUID(value or "")
        if parsed.version == 4 and str(parsed) == value:
            return value, False
    except ValueError:
        pass
    return str(uuid4()), True


def download_event(file_id: str) -> UsageEventType | None:
    kind, separator, identifier = file_id.partition("-")
    if not separator or kind not in {"gift", "rate"}:
        return None
    try:
        if str(UUID(identifier)) != identifier:
            return None
    except ValueError:
        return None
    return UsageEventType.GIFT_PDF_DOWNLOAD if kind == "gift" else UsageEventType.RATE_PDF_DOWNLOAD


class UsageService:
    def __init__(
        self, repository: UsageRepository, *, clock: Callable[[], float] | None = None
    ) -> None:
        self.repository = repository
        self.clock = clock or time.time

    def record_client(self, event: ClientUsageEvent, visitor_id: str) -> None:
        if event.event_type == UsageEventType.PAGE_VIEW:
            valid = event.source == "site" and event.target is None
        else:
            valid = event.source in {"header", "feedback"} and event.target in {"fairy", "github"}
        if not valid:
            raise UsageError("통계 이벤트 형식을 확인해 주세요.")
        self.record(
            event.event_type,
            visitor_id,
            event_id=str(event.event_id),
            source=event.source,
            target=event.target,
        )

    def record(
        self,
        event_type: UsageEventType,
        visitor_id: str,
        *,
        event_id: str | None = None,
        source: str | None = None,
        target: str | None = None,
    ) -> None:
        now = int(self.clock())
        self.repository.record(
            event_id=event_id or str(uuid4()),
            event_type=event_type,
            visitor_id=visitor_id,
            occurred_at=now,
            day=datetime.fromtimestamp(now, KOREA).date().isoformat(),
            source=source,
            target=target,
        )

    def summary(self, days: int = 30) -> UsageSummary:
        if days not in (7, 30, 90):
            raise UsageError("조회 기간은 7일, 30일 또는 90일이어야 합니다.")
        today = datetime.fromtimestamp(self.clock(), KOREA).date()
        first_day = today - timedelta(days=days - 1)
        start = datetime.combine(first_day, day_time(), KOREA)
        end = datetime.combine(today + timedelta(days=1), day_time(), KOREA)
        rows = self.repository.summary(
            start=int(start.timestamp()),
            end=int(end.timestamp()),
            first_day=first_day.isoformat(),
            last_day=today.isoformat(),
            utc_offset=int(start.utcoffset().total_seconds()),
        )
        daily = {
            (first_day + timedelta(days=index)).isoformat(): DailyUsage(
                day=first_day + timedelta(days=index)
            )
            for index in range(days)
        }
        totals = UsageCounts()
        for day, event_type, count in rows.counts:
            field = EVENT_FIELDS[UsageEventType(event_type)]
            setattr(daily[day], field, count)
            setattr(totals, field, getattr(totals, field) + count)
        for event_type, count in rows.unique_visitors:
            setattr(totals, VISITOR_FIELDS[event_type], count)
        for bucket, event_type, count in rows.daily_visitors:
            day = (date(1970, 1, 1) + timedelta(days=bucket)).isoformat()
            setattr(daily[day], VISITOR_FIELDS[event_type], count)
        return UsageSummary(
            period_days=days,
            period_start=first_day,
            period_end=today,
            totals=totals,
            daily=list(daily.values()),
        )
