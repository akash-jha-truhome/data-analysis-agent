"""Pydantic request/response models for the analysis API (spec/api.md)."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class AskRequest(BaseModel):
    # Optional at the model level so we can return a 400 (per spec/api.md) rather
    # than FastAPI's default 422 when a field is missing/blank.
    dataset_id: str = ""
    question: str = ""
    # Phase 2: continue an existing multi-turn session. None -> a new session.
    session_id: str | None = None
    # Phase 3: load several datasets into the session for a cross-file question.
    # When present it supersedes the single dataset_id for loading (dataset_id
    # remains the primary/anchor). None -> just [dataset_id].
    dataset_ids: list[str] | None = None
    # Phase 3: the user's reply to a prior clarifying question. When set the
    # agent writes code instead of clarifying again.
    clarification_answer: str | None = None


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _clarification_from_steps(steps: Any) -> str | None:
    """Pull the clarifying question out of the ``clarify_request`` trace entry."""
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("action") == "clarify_request":
            q = step.get("clarification_question")
            if isinstance(q, str) and q.strip():
                return q.strip()
    return None


def run_row_to_payload(row: Any, *, include_meta: bool = False) -> dict:
    """Build the /ask (and GET /runs) response payload from a RunRow.

    ``include_meta`` adds question/dataset_id/created_at/error_message for the
    audit-record endpoint.
    """
    steps = _loads(row.step_trace_json) or []
    needs_clarification = row.status == "needs_clarification"
    clarification = _clarification_from_steps(steps) if needs_clarification else None
    payload: dict = {
        "run_id": row.id,
        "session_id": row.session_id,
        "status": row.status,
        "needs_clarification": needs_clarification,
        "clarification": clarification,
        "answer": row.answer_text,
        "key_numbers": _loads(row.key_numbers_json) or [],
        "chart": _loads(row.chart_json),
        "table": _loads(row.result_json),
        "code": row.generated_code,
        "steps": steps,
        # Phase 2 insights.
        "suggestions": _loads(row.suggestions_json) or [],
        "data_quality": _loads(row.data_quality_json),
        "tokens": {
            "prompt": row.prompt_tokens or 0,
            "completion": row.completion_tokens or 0,
            "total": row.total_tokens or 0,
        },
    }
    if include_meta:
        payload.update(
            {
                "question": row.question,
                "dataset_id": row.dataset_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "error_message": row.error_message,
            }
        )
    return payload
