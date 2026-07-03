"""datasets table + extended runs audit columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_RUN_COLUMNS = [
    ("dataset_id", sa.Text()),
    ("session_id", sa.Text()),
    ("question", sa.Text()),
    ("generated_code", sa.Text()),
    ("result_json", sa.Text()),
    ("answer_text", sa.Text()),
    ("key_numbers_json", sa.Text()),
    ("chart_json", sa.Text()),
    ("step_trace_json", sa.Text()),
    ("prompt_tokens", sa.Integer()),
    ("completion_tokens", sa.Integer()),
    ("total_tokens", sa.Integer()),
]


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("parquet_path", sa.Text(), nullable=False),
        sa.Column("n_rows", sa.Integer(), nullable=False),
        sa.Column("n_cols", sa.Integer(), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("sample_rows_json", sa.Text(), nullable=False),
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

    op.drop_table("datasets")
