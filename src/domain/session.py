"""Pydantic response models for the run-history / sessions API (spec/api.md)."""
from __future__ import annotations

from pydantic import BaseModel


class SessionSummary(BaseModel):
    """Response for ``GET /sessions/{session_id}``."""

    session_id: str
    dataset_id: str | None
    total_tokens: int
    run_count: int
    created_at: str | None


class SessionRunItem(BaseModel):
    """One run summary in a session's run history."""

    run_id: str
    question: str | None
    status: str
    total_tokens: int
    created_at: str | None


class SessionRunsResponse(BaseModel):
    """Response for ``GET /sessions/{session_id}/runs``."""

    session_id: str
    dataset_id: str | None
    total_tokens: int
    runs: list[SessionRunItem]
