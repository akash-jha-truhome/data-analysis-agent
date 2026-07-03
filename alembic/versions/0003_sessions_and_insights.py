"""sessions + messages tables + runs insight columns (Phase 2)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_RUN_COLUMNS = [
    ("suggestions_json", sa.Text()),
    ("data_quality_json", sa.Text()),
]


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("runs") as batch:
        for name, col_type in _NEW_RUN_COLUMNS:
            batch.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        for name, _ in reversed(_NEW_RUN_COLUMNS):
            batch.drop_column(name)

    op.drop_table("messages")
    op.drop_table("sessions")
