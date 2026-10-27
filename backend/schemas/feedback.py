"""Pydantic request and response contracts for private feedback."""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool


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
    email_consent: StrictBool = False
    source: FeedbackSource = FeedbackSource.GENERAL
    website: str = Field(default="", max_length=200, description="스팸 방지용 빈 필드")


class FeedbackReceipt(BaseModel):
    id: UUID
    message: str = "의견을 남겨 주셔서 감사합니다."


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
