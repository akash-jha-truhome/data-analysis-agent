"""Session run-history endpoints (spec/api.md — Phase 2).

Powers the run-history browser + the running session token total. The
authoritative session ``total_tokens`` is computed as the SUM of the member
runs' ``total_tokens`` (robust even if a stored session counter drifts).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api._common import ok, api_error
from db.session import get_session
from db.models import RunRow, SessionRow
from domain.session import SessionRunItem, SessionRunsResponse, SessionSummary

router = APIRouter()


def _load_session(session: Session, session_id: str) -> SessionRow:
    row = session.get(SessionRow, session_id)
    if row is None:
        raise api_error("UNKNOWN_SESSION", f"Session {session_id} not found", 404)
    return row


@router.get("/sessions/{session_id}")
def get_session_summary(
    session_id: str, session: Session = Depends(get_session)
) -> dict:
    row = _load_session(session, session_id)

    total_tokens, run_count = session.execute(
        select(
            func.coalesce(func.sum(RunRow.total_tokens), 0),
            func.count(RunRow.id),
        ).where(RunRow.session_id == session_id)
    ).one()

    summary = SessionSummary(
        session_id=row.id,
        dataset_id=row.dataset_id,
        total_tokens=int(total_tokens or 0),
        run_count=int(run_count or 0),
        created_at=row.created_at.isoformat() if row.created_at else None,
    )
    return ok(summary.model_dump())


@router.get("/sessions/{session_id}/runs")
def get_session_runs(
    session_id: str, session: Session = Depends(get_session)
) -> dict:
    row = _load_session(session, session_id)

    runs = (
        session.execute(
            select(RunRow)
            .where(RunRow.session_id == session_id)
            .order_by(RunRow.created_at.desc())
        )
        .scalars()
        .all()
    )

    items = [
        SessionRunItem(
            run_id=r.id,
            question=r.question,
            status=r.status,
            total_tokens=int(r.total_tokens or 0),
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in runs
    ]
    total_tokens = sum(item.total_tokens for item in items)

    response = SessionRunsResponse(
        session_id=row.id,
        dataset_id=row.dataset_id,
        total_tokens=total_tokens,
        runs=items,
    )
    return ok(response.model_dump())
