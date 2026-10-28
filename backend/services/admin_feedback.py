"""Private feedback review, date filtering, and retention-aware output."""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from uuid import UUID

from dateutil.relativedelta import relativedelta

from backend.schemas.feedback import (
    FeedbackFilters,
    FeedbackPage,
    FeedbackRecord,
    FeedbackStatus,
    FeedbackStatusReceipt,
)
from backend.services.feedback import FeedbackError
from backend.services.usage import KOREA
from backend.storage.feedback import AdminFeedbackRepository

PAGE_SIZE = 50


class AdminFeedbackService:
    def __init__(
        self, repository: AdminFeedbackRepository, *, clock: Callable[[], float] | None = None
    ) -> None:
        self.repository = repository
        self.clock = clock or time.time

    def _retention_cutoff(self, now: int) -> int:
        return int((datetime.fromtimestamp(now, UTC) - relativedelta(years=1)).timestamp())

    def list(self, filters: FeedbackFilters) -> FeedbackPage:
        now = int(self.clock())
        today = datetime.fromtimestamp(now, KOREA).date()
        end = filters.end_date or today
        if end > today or (filters.start_date is not None and filters.start_date > end):
            raise FeedbackError(
                "INVALID_PERIOD",
                "조회 시작일과 종료일을 확인해 주세요. 종료일은 오늘까지 선택할 수 있습니다.",
            )
        rows = self.repository.list(
            after=self._retention_cutoff(now),
            before=int(datetime.combine(end + timedelta(days=1), day_time(), KOREA).timestamp()),
            start=int(datetime.combine(filters.start_date, day_time(), KOREA).timestamp())
            if filters.start_date
            else None,
            contact_after=now,
            offset=(filters.page - 1) * PAGE_SIZE,
            limit=PAGE_SIZE,
            category=filters.category,
            satisfaction=filters.satisfaction,
            status=filters.status,
        )
        return FeedbackPage(
            page=filters.page,
            total=rows.total,
            items=[
                FeedbackRecord(
                    id=row.id,
                    satisfaction=row.satisfaction,
                    category=row.category,
                    message=row.message,
                    source=row.source,
                    status=row.status,
                    created_at=datetime.fromtimestamp(row.created_at, UTC),
                    email=row.email,
                    email_expires_at=datetime.fromtimestamp(row.email_expires_at, UTC)
                    if row.email_expires_at is not None
                    else None,
                )
                for row in rows.items
            ],
        )

    def change_status(self, identifier: UUID, status: FeedbackStatus) -> FeedbackStatusReceipt:
        if not self.repository.change_status(
            str(identifier), status, after=self._retention_cutoff(int(self.clock()))
        ):
            raise FeedbackError(
                "NOT_FOUND", "의견이 없거나 보관 기간이 지났습니다.", status_code=404
            )
        return FeedbackStatusReceipt(id=identifier, status=status)

    def delete(self, identifier: UUID) -> None:
        if not self.repository.delete(
            str(identifier), after=self._retention_cutoff(int(self.clock()))
        ):
            raise FeedbackError(
                "NOT_FOUND", "의견이 없거나 보관 기간이 지났습니다.", status_code=404
            )
