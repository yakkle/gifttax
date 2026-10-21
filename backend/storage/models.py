"""SQLAlchemy persistence models; API contracts are defined in backend.schemas."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, LargeBinary, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    __table_args__ = {"sqlite_strict": True}


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("satisfaction IN ('satisfied', 'neutral', 'dissatisfied')"),
        CheckConstraint("category IN ('review', 'problem', 'suggestion')"),
        CheckConstraint("length(message) <= 2000"),
        CheckConstraint("source IN ('general', 'result', 'error')"),
        CheckConstraint("status IN ('new', 'in_progress', 'resolved')"),
        CheckConstraint("satisfaction IS NOT NULL OR length(trim(message)) > 0"),
        Index("feedback_created_at", "created_at"),
        {"sqlite_strict": True},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    satisfaction: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, server_default=text("''"))
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'new'"))
    created_at: Mapped[int] = mapped_column(Integer)
    contact: Mapped[FeedbackContact | None] = relationship(
        back_populates="feedback", cascade="all, delete-orphan", passive_deletes=True
    )


class FeedbackContact(Base):
    __tablename__ = "feedback_contacts"
    __table_args__ = (
        CheckConstraint("length(email) BETWEEN 1 AND 254"),
        CheckConstraint("expires_at > consented_at"),
        Index("feedback_contacts_expiry", "expires_at"),
        {"sqlite_strict": True},
    )

    feedback_id: Mapped[str] = mapped_column(
        Text, ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(Text)
    consented_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    feedback: Mapped[Feedback] = relationship(back_populates="contact")


_USAGE_EVENT_CHECK = (
    "event_type IN ('page_view', 'calculation_success', 'calculation_failure', "
    "'gift_pdf_download', 'rate_pdf_download', 'feedback_submitted', 'support_click')"
)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(_USAGE_EVENT_CHECK),
        CheckConstraint("source IN ('site', 'header', 'feedback')"),
        CheckConstraint("target IN ('fairy', 'github')"),
        Index("usage_events_time", "occurred_at", "event_type", "visitor_id"),
        {"sqlite_strict": True},
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    visitor_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[int] = mapped_column(Integer)


class DailyUsageCount(Base):
    __tablename__ = "daily_usage_counts"
    __table_args__ = (
        CheckConstraint(_USAGE_EVENT_CHECK),
        CheckConstraint("event_count >= 0"),
        {"sqlite_strict": True},
    )

    day: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, primary_key=True)
    event_count: Mapped[int] = mapped_column(Integer)


class AdminAccount(Base):
    __tablename__ = "admin_account"
    __table_args__ = (CheckConstraint("id = 1"), {"sqlite_strict": True})

    # Match the original SQLite INTEGER PRIMARY KEY reflection exactly.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=True)
    user_handle: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[int] = mapped_column(Integer)
    credentials: Mapped[list[AdminCredential]] = relationship(back_populates="account")
    sessions: Mapped[list[AdminSession]] = relationship(back_populates="account")


class AdminCredential(Base):
    __tablename__ = "admin_credentials"
    __table_args__ = (CheckConstraint("sign_count >= 0"), {"sqlite_strict": True})

    credential_id: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_account.id"))
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer)
    transports_json: Mapped[str] = mapped_column(Text, server_default=text("'[]'"))
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)
    last_used_at: Mapped[int | None] = mapped_column(Integer)
    account: Mapped[AdminAccount] = relationship(back_populates="credentials")


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at"),
        Index("admin_sessions_expiry", "expires_at"),
        {"sqlite_strict": True},
    )

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_account.id"))
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    account: Mapped[AdminAccount] = relationship(back_populates="sessions")


class AdminOneTimeToken(Base):
    __tablename__ = "admin_one_time_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('registration', 'login')"),
        CheckConstraint("expires_at > created_at"),
        Index("admin_one_time_tokens_expiry", "expires_at"),
        {"sqlite_strict": True},
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    purpose: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)


class AdminChallenge(Base):
    __tablename__ = "admin_challenges"
    __table_args__ = (
        CheckConstraint("purpose IN ('registration', 'authentication')"),
        CheckConstraint("expires_at > created_at"),
        Index("admin_challenges_expiry", "expires_at"),
        {"sqlite_strict": True},
    )

    challenge_id: Mapped[str] = mapped_column(Text, primary_key=True)
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    purpose: Mapped[str] = mapped_column(Text)
    binding_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
