"""session_datasets join table (Phase 3 — multi-file / multi-sheet)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_datasets",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("var_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "dataset_id", name="uq_session_dataset"),
    )


def downgrade() -> None:
    op.drop_table("session_datasets")
