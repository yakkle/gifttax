"""Pydantic request and response contracts for feedback and usage reporting."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Satisfaction(StrEnum):
    SATISFIED = "satisfied"
    NEUTRAL = "neutral"
    DISSATISFIED = "dissatisfied"


class FeedbackCategory(StrEnum):
    REVIEW = "review"
    PROBLEM = "problem"
    SUGGESTION = "suggestion"


class FeedbackStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class FeedbackSource(StrEnum):
    GENERAL = "general"
    RESULT = "result"
    ERROR = "error"


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    submission_id: UUID
    satisfaction: Satisfaction | None = None
    category: FeedbackCategory = FeedbackCategory.REVIEW
    message: str = Field(default="", max_length=2000)
    email: str | None = Field(default=None, max_length=254)
    email_consent: bool = False
    source: FeedbackSource = FeedbackSource.GENERAL


class FeedbackRecord(BaseModel):
    id: UUID
    satisfaction: Satisfaction | None
    category: FeedbackCategory
    message: str
    source: FeedbackSource
    status: FeedbackStatus
    created_at: AwareDatetime
    email: str | None = None
    email_expires_at: AwareDatetime | None = None


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
