"""Allowlisted public events and private usage summaries."""

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UsageEventType(StrEnum):
    PAGE_VIEW = "page_view"
    CALCULATION_SUCCESS = "calculation_success"
    CALCULATION_FAILURE = "calculation_failure"
    GIFT_PDF_DOWNLOAD = "gift_pdf_download"
    RATE_PDF_DOWNLOAD = "rate_pdf_download"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    SUPPORT_CLICK = "support_click"


class ClientUsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal[UsageEventType.PAGE_VIEW, UsageEventType.SUPPORT_CLICK]
    source: Literal["site", "header", "feedback"] = "site"
    target: Literal["fairy", "github"] | None = None


class UsageCounts(BaseModel):
    page_views: int = Field(default=0, ge=0)
    visitors: int = Field(default=0, ge=0)
    calculation_successes: int = Field(default=0, ge=0)
    calculation_failures: int = Field(default=0, ge=0)
    calculation_users: int = Field(default=0, ge=0)
    gift_pdf_downloads: int = Field(default=0, ge=0)
    rate_pdf_downloads: int = Field(default=0, ge=0)
    feedback_submissions: int = Field(default=0, ge=0)
    support_clicks: int = Field(default=0, ge=0)


class DailyUsage(UsageCounts):
    day: date


class UsageSummary(BaseModel):
    period_days: Literal[7, 30, 90]
    period_start: date
    period_end: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    totals: UsageCounts
    daily: list[DailyUsage]
