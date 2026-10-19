"""Normalize the legacy inline contact foreign key for reliable reflection.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not op.get_context().as_sql:
        foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys("feedback_contacts")
        if any(fk["options"].get("ondelete") == "CASCADE" for fk in foreign_keys):
            return

    # Frozen snapshot: preserve checks, defaults, index, and cascading deletion.
    # Do not import live ORM models into historical migrations.
    metadata = sa.MetaData()
    sa.Table("feedback", metadata, sa.Column("id", sa.Text(), primary_key=True))
    contacts = sa.Table(
        "feedback_contacts",
        metadata,
        sa.Column(
            "feedback_id",
            sa.Text(),
            sa.ForeignKey("feedback.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(email) BETWEEN 1 AND 254"),
        sa.CheckConstraint("expires_at > consented_at"),
        sa.Index("feedback_contacts_expiry", "expires_at"),
        sqlite_strict=True,
    )
    with op.batch_alter_table(
        "feedback_contacts",
        recreate="always",
        copy_from=contacts,
        table_kwargs={"sqlite_strict": True},
    ):
        pass


def downgrade() -> None:
    # Normalization changes SQL syntax only; the 0001 schema semantics are retained.
    pass
