"""ORM operations for private feedback; validation belongs to the service."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, select, update
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


@dataclass(frozen=True)
class StoredFeedback:
    id: str
    satisfaction: str | None
    category: str
    message: str
    source: str
    status: str
    created_at: int
    email: str | None
    email_expires_at: int | None


@dataclass(frozen=True)
class FeedbackPageRows:
    items: list[StoredFeedback]
    total: int


class AdminFeedbackRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(
        self,
        *,
        after: int,
        before: int,
        contact_after: int,
        offset: int,
        limit: int,
        start: int | None = None,
        category: str | None = None,
        satisfaction: str | None = None,
        status: str | None = None,
    ) -> FeedbackPageRows:
        conditions = [Feedback.created_at > after, Feedback.created_at < before]
        if start is not None:
            conditions.append(Feedback.created_at >= start)
        for column, value in (
            (Feedback.category, category),
            (Feedback.satisfaction, satisfaction),
            (Feedback.status, status),
        ):
            if value is not None:
                conditions.append(column == value)
        query = (
            select(
                Feedback.id,
                Feedback.satisfaction,
                Feedback.category,
                Feedback.message,
                Feedback.source,
                Feedback.status,
                Feedback.created_at,
                FeedbackContact.email,
                FeedbackContact.expires_at,
            )
            .outerjoin(
                FeedbackContact,
                and_(
                    FeedbackContact.feedback_id == Feedback.id,
                    FeedbackContact.expires_at > contact_after,
                ),
            )
            .where(*conditions)
            .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        )
        with self.database.session() as session:
            total = session.scalar(select(func.count()).select_from(Feedback).where(*conditions))
            items = [
                StoredFeedback(*row) for row in session.execute(query.offset(offset).limit(limit))
            ]
            return FeedbackPageRows(items, total)

    def change_status(self, identifier: str, status: str, *, after: int) -> bool:
        with self.database.session(write=True) as session:
            result = session.execute(
                update(Feedback)
                .where(Feedback.id == identifier, Feedback.created_at > after)
                .values(status=status)
            )
            return result.rowcount == 1

    def delete(self, identifier: str, *, after: int) -> bool:
        with self.database.session(write=True) as session:
            result = session.execute(
                delete(Feedback).where(Feedback.id == identifier, Feedback.created_at > after)
            )
            return result.rowcount == 1
