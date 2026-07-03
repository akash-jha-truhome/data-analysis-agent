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


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def run_row_to_payload(row: Any, *, include_meta: bool = False) -> dict:
    """Build the /ask (and GET /runs) response payload from a RunRow.

    ``include_meta`` adds question/dataset_id/created_at/error_message for the
    audit-record endpoint.
    """
    payload: dict = {
        "run_id": row.id,
        "session_id": row.session_id,
        "status": row.status,
        "answer": row.answer_text,
        "key_numbers": _loads(row.key_numbers_json) or [],
        "chart": _loads(row.chart_json),
        "table": _loads(row.result_json),
        "code": row.generated_code,
        "steps": _loads(row.step_trace_json) or [],
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
