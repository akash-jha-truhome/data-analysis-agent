"""POST /ask — run the code-execution loop over a loaded dataset (spec/api.md)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.session import get_session
from db.models import RunRow
from domain.run import AskRequest, run_row_to_payload
from datasets.store import get_dataset_meta
from graph.runner import run_agent

router = APIRouter()


@router.post("/ask")
def ask(req: AskRequest, session: Session = Depends(get_session)) -> dict:
    dataset_id = (req.dataset_id or "").strip()
    question = (req.question or "").strip()
    if not dataset_id or not question:
        raise api_error("BAD_REQUEST", "Both dataset_id and question are required.", 400)

    if get_dataset_meta(dataset_id) is None:
        raise api_error("UNKNOWN_DATASET", f"Dataset {dataset_id} not found.", 400)

    session_id = (req.session_id or "").strip() or None

    # Phase 3 — additional datasets to load into the session (cross-file question).
    dataset_ids = [d.strip() for d in (req.dataset_ids or []) if d and d.strip()]
    if dataset_id not in dataset_ids:
        dataset_ids = [dataset_id, *dataset_ids]
    for did in dataset_ids:
        if get_dataset_meta(did) is None:
            raise api_error("UNKNOWN_DATASET", f"Dataset {did} not found.", 400)

    clarification_answer = (req.clarification_answer or "").strip() or None

    try:
        run_id = run_agent(
            dataset_id,
            question,
            session_id=session_id,
            dataset_ids=dataset_ids,
            clarification_answer=clarification_answer,
        )
    except Exception as exc:  # sandbox infra / LLM hard failure surfaced by runner
        raise api_error("AGENT_FAILURE", f"Agent run failed: {exc}", 500)

    run = session.get(RunRow, run_id)
    if run is None:
        raise api_error("INTERNAL", "Run vanished after execution.", 500)

    # needs_clarification is a normal 200 outcome (the UI shows the question) —
    # NOT an error and NOT a fabricated answer.
    if run.status == "failed":
        # Could not produce runnable code within max_steps — NEVER a fabricated number.
        raise api_error(
            "AGENT_COULD_NOT_ANSWER",
            run.error_message or "The agent could not produce a runnable answer.",
            422,
        )

    return ok(run_row_to_payload(run))
