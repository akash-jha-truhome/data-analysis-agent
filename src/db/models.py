from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Integer, Text, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")

    # --- Skeleton compatibility (retained, nullable) ---
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Analysis audit trail (spec/data.md) ---
    dataset_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_numbers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    chart_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_trace_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Phase 2 insights (spec/data.md) ---
    suggestions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_quality_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class SessionRow(Base):
    """A multi-turn analysis session over a loaded dataset (Phase 2)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class MessageRow(Base):
    """One conversation turn (user question or assistant answer) (Phase 2)."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class SessionDatasetRow(Base):
    """Join table linking datasets to a session (Phase 3 — multi-file).

    ``var_name`` is the python variable the dataframe is exposed as in the
    sandbox/prompt (e.g. ``df`` for the first dataset, ``orders_2024`` for the
    next). Unique per (session, dataset).
    """

    __tablename__ = "session_datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    var_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )

    __table_args__ = (
        UniqueConstraint("session_id", "dataset_id", name="uq_session_dataset"),
    )


class DatasetRow(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    parquet_path: Mapped[str] = mapped_column(Text, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, nullable=False)
    sample_rows_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
