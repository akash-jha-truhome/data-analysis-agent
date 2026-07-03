"""Session run-history API — GET /sessions/{id} and /sessions/{id}/runs.

Seeds the DB directly (no LLM). Uses the isolated tmp SQLite DB via the autouse
``_isolated_db`` conftest fixture. ``SessionRow`` is created by the concurrent
agent-core slice (migration 0003); until that lands these tests are
pending-integration — the structure/signatures are correct now.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

# SessionRow is owned by the agent-core slice; import so full green requires
# integration but the contract is pinned here now.
from db.models import RunRow, SessionRow
from api import create_app


def _mk_run(session_id, dataset_id, question, status, total, created_at):
    return RunRow(
        session_id=session_id,
        dataset_id=dataset_id,
        question=question,
        status=status,
        total_tokens=total,
        prompt_tokens=total,
        completion_tokens=0,
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.fixture
def seeded(_isolated_db):
    """Seed one session with two runs (completed + failed) and return ids."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=_isolated_db, autoflush=False, autocommit=False)
    base = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)
    with factory() as s:
        sess = SessionRow(dataset_id="ds-1", total_tokens=0, created_at=base)
        s.add(sess)
        s.flush()
        session_id = sess.id

        older = _mk_run(session_id, "ds-1", "total revenue", "completed", 820, base)
        newer = _mk_run(
            session_id, "ds-1", "revenue by region", "failed", 1300,
            base + timedelta(minutes=5),
        )
        s.add_all([older, newer])
        s.commit()
        run_ids = {"older": older.id, "newer": newer.id}

    return {"session_id": session_id, "run_ids": run_ids}


@pytest.fixture
def client(_isolated_db):
    with TestClient(create_app()) as c:
        yield c


def test_session_summary_sums_run_tokens(client, seeded):
    sid = seeded["session_id"]
    resp = client.get(f"/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["session_id"] == sid
    assert data["dataset_id"] == "ds-1"
    # Authoritative total = SUM of run totals (820 + 1300).
    assert data["total_tokens"] == 2120
    assert data["run_count"] == 2
    assert data["created_at"] is not None


def test_session_runs_newest_first(client, seeded):
    sid = seeded["session_id"]
    resp = client.get(f"/sessions/{sid}/runs")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] == sid
    assert data["dataset_id"] == "ds-1"
    assert data["total_tokens"] == 2120

    runs = data["runs"]
    assert len(runs) == 2
    # Newest first: the failed run (base+5m) precedes the completed one.
    assert runs[0]["run_id"] == seeded["run_ids"]["newer"]
    assert runs[1]["run_id"] == seeded["run_ids"]["older"]
    first = runs[0]
    assert set(first) == {"run_id", "question", "status", "total_tokens", "created_at"}
    assert first["question"] == "revenue by region"
    assert first["status"] == "failed"
    assert first["total_tokens"] == 1300
    assert first["created_at"] is not None


def test_unknown_session_summary_404(client):
    resp = client.get("/sessions/does-not-exist")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "UNKNOWN_SESSION"
    assert "message" in detail


def test_unknown_session_runs_404(client):
    resp = client.get("/sessions/does-not-exist/runs")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "UNKNOWN_SESSION"


def test_session_with_no_runs_is_zeroed(client, _isolated_db):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=_isolated_db, autoflush=False, autocommit=False)
    with factory() as s:
        sess = SessionRow(dataset_id="ds-empty", total_tokens=0)
        s.add(sess)
        s.commit()
        sid = sess.id

    resp = client.get(f"/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_tokens"] == 0
    assert data["run_count"] == 0

    runs = client.get(f"/sessions/{sid}/runs").json()["data"]["runs"]
    assert runs == []
