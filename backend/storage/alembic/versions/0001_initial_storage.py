"""initial storage

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.storage.schema import is_legacy_schema

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if (
        not op.get_context().as_sql
        and op.get_bind().dialect.name == "sqlite"
        and is_legacy_schema(op.get_bind())
    ):
        return

    op.create_table(
        "admin_account",
        sa.Column("id", sa.Integer(), nullable=True),
        sa.Column("user_handle", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_handle"),
        sqlite_strict=True,
    )
    op.create_table(
        "admin_challenges",
        sa.Column("challenge_id", sa.Text(), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("binding_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("purpose IN ('registration', 'authentication')"),
        sa.CheckConstraint("expires_at > created_at"),
        sa.PrimaryKeyConstraint("challenge_id"),
        sqlite_strict=True,
    )
    with op.batch_alter_table("admin_challenges", schema=None) as batch_op:
        batch_op.create_index("admin_challenges_expiry", ["expires_at"], unique=False)

    op.create_table(
        "admin_one_time_tokens",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("purpose IN ('registration', 'login')"),
        sa.CheckConstraint("expires_at > created_at"),
        sa.PrimaryKeyConstraint("token_hash"),
        sqlite_strict=True,
    )
    with op.batch_alter_table("admin_one_time_tokens", schema=None) as batch_op:
        batch_op.create_index("admin_one_time_tokens_expiry", ["expires_at"], unique=False)

    op.create_table(
        "daily_usage_counts",
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('page_view', 'calculation_success', 'calculation_failure', 'gift_pdf_download', 'rate_pdf_download', 'feedback_submitted', 'support_click')"
        ),
        sa.CheckConstraint("event_count >= 0"),
        sa.PrimaryKeyConstraint("day", "event_type"),
        sqlite_strict=True,
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("satisfaction", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), server_default=sa.text("('')"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("category IN ('review', 'problem', 'suggestion')"),
        sa.CheckConstraint("satisfaction IN ('satisfied', 'neutral', 'dissatisfied')"),
        sa.CheckConstraint("source IN ('general', 'result', 'error')"),
        sa.CheckConstraint("status IN ('new', 'in_progress', 'resolved')"),
        sa.CheckConstraint("length(message) <= 2000"),
        sa.CheckConstraint("satisfaction IS NOT NULL OR length(trim(message)) > 0"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_strict=True,
    )
    with op.batch_alter_table("feedback", schema=None) as batch_op:
        batch_op.create_index("feedback_created_at", ["created_at"], unique=False)

    op.create_table(
        "usage_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("visitor_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('page_view', 'calculation_success', 'calculation_failure', 'gift_pdf_download', 'rate_pdf_download', 'feedback_submitted', 'support_click')"
        ),
        sa.CheckConstraint("source IN ('site', 'header', 'feedback')"),
        sa.CheckConstraint("target IN ('fairy', 'github')"),
        sa.PrimaryKeyConstraint("event_id"),
        sqlite_strict=True,
    )
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.create_index(
            "usage_events_time", ["occurred_at", "event_type", "visitor_id"], unique=False
        )

    op.create_table(
        "admin_credentials",
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("transports_json", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.CheckConstraint("sign_count >= 0"),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_account.id"],
        ),
        sa.PrimaryKeyConstraint("credential_id"),
        sqlite_strict=True,
    )
    op.create_table(
        "admin_sessions",
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("expires_at > created_at"),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_account.id"],
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sqlite_strict=True,
    )
    with op.batch_alter_table("admin_sessions", schema=None) as batch_op:
        batch_op.create_index("admin_sessions_expiry", ["expires_at"], unique=False)

    op.create_table(
        "feedback_contacts",
        sa.Column("feedback_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("expires_at > consented_at"),
        sa.CheckConstraint("length(email) BETWEEN 1 AND 254"),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("feedback_id"),
        sqlite_strict=True,
    )
    with op.batch_alter_table("feedback_contacts", schema=None) as batch_op:
        batch_op.create_index("feedback_contacts_expiry", ["expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("feedback_contacts", schema=None) as batch_op:
        batch_op.drop_index("feedback_contacts_expiry")

    op.drop_table("feedback_contacts")
    with op.batch_alter_table("admin_sessions", schema=None) as batch_op:
        batch_op.drop_index("admin_sessions_expiry")

    op.drop_table("admin_sessions")
    op.drop_table("admin_credentials")
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.drop_index("usage_events_time")

    op.drop_table("usage_events")
    with op.batch_alter_table("feedback", schema=None) as batch_op:
        batch_op.drop_index("feedback_created_at")

    op.drop_table("feedback")
    op.drop_table("daily_usage_counts")
    with op.batch_alter_table("admin_one_time_tokens", schema=None) as batch_op:
        batch_op.drop_index("admin_one_time_tokens_expiry")

    op.drop_table("admin_one_time_tokens")
    with op.batch_alter_table("admin_challenges", schema=None) as batch_op:
        batch_op.drop_index("admin_challenges_expiry")

    op.drop_table("admin_challenges")
    op.drop_table("admin_account")
    if op.get_context().dialect.name == "sqlite":
        op.execute("PRAGMA user_version = 0")
