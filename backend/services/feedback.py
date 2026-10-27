"""Anonymous feedback submission, consent, retention, and retry handling."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from email_validator import EmailNotValidError, validate_email

from backend.schemas.feedback import FeedbackCreate
from backend.services.retention import email_expiry
from backend.storage.feedback import FeedbackRepository


class FeedbackError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FeedbackSubmission:
    id: UUID
    created: bool


def normalize_email(value: str | None, consent: bool) -> str | None:
    if not value:
        return None
    if not consent:
        raise FeedbackError("EMAIL_CONSENT_REQUIRED", "답변용 이메일 수집에 동의해 주세요.")
    try:
        normalized = validate_email(value, check_deliverability=False).normalized
        if len(normalized) > 254:
            raise ValueError("Normalized address is too long")
        return normalized
    except (EmailNotValidError, ValueError) as error:
        raise FeedbackError("INVALID_EMAIL", "이메일 주소를 확인해 주세요.") from error


class FeedbackService:
    def __init__(
        self, repository: FeedbackRepository, *, clock: Callable[[], float] | None = None
    ) -> None:
        self.repository = repository
        self.clock = clock or time.time

    def submit(self, input_data: FeedbackCreate) -> FeedbackSubmission:
        # Bots that populate the hidden field receive an ordinary receipt without a write.
        if input_data.website:
            return FeedbackSubmission(input_data.submission_id, created=True)
        if input_data.satisfaction is None and not input_data.message:
            raise FeedbackError("EMPTY_FEEDBACK", "만족도를 선택하거나 의견을 작성해 주세요.")
        email = normalize_email(input_data.email, input_data.email_consent)
        now = int(self.clock())

        with self.repository.transaction() as records:
            # The write transaction serializes concurrent retries. A used ID never updates a row.
            if records.contains(str(input_data.submission_id)):
                return FeedbackSubmission(input_data.submission_id, created=False)
            records.add(
                submission_id=str(input_data.submission_id),
                satisfaction=input_data.satisfaction,
                category=input_data.category,
                message=input_data.message,
                source=input_data.source,
                created_at=now,
                email=email,
                email_expires_at=int(email_expiry(datetime.fromtimestamp(now, UTC)).timestamp()),
            )
        return FeedbackSubmission(input_data.submission_id, created=True)
