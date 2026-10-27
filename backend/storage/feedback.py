"""ORM operations for private feedback; validation belongs to the service."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from backend.storage.database import Database
from backend.storage.models import Feedback, FeedbackContact


class FeedbackRecords:
    def __init__(self, session: Session) -> None:
        self.session = session

    def contains(self, submission_id: str) -> bool:
        return self.session.get(Feedback, submission_id) is not None

    def add(
        self,
        *,
        submission_id: str,
        satisfaction: str | None,
        category: str,
        message: str,
        source: str,
        created_at: int,
        email: str | None,
        email_expires_at: int,
    ) -> None:
        feedback = Feedback(
            id=submission_id,
            satisfaction=satisfaction,
            category=category,
            message=message,
            source=source,
            created_at=created_at,
        )
        if email is not None:
            feedback.contact = FeedbackContact(
                email=email,
                consented_at=created_at,
                expires_at=email_expires_at,
            )
        self.session.add(feedback)
        self.session.flush()


class FeedbackRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[FeedbackRecords]:
        with self.database.session(write=True) as session:
            yield FeedbackRecords(session)
