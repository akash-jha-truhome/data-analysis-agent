"""Runner: create a pending RunRow, invoke the graph, return the run_id.

The graph's ``finalize`` / ``handle_error`` nodes persist the final state onto
the same RunRow, so callers read the row (or use GET /runs/{id}) for the result.

Phase 2: a run belongs to a multi-turn ``SessionRow``. When ``session_id`` is
None the runner opens a new session bound to the dataset; otherwise it loads the
session's prior ``MessageRow``s as conversation memory (TEXT ONLY) so follow-up
questions resolve against context. After the run it persists the user + assistant
turns and accumulates the session's token total.
"""
import re
from pathlib import Path

from graph.agent import compiled_graph
from graph.state import AgentState
from config.settings import get_settings
from db.session import create_db_session
from db.models import RunRow, SessionRow, MessageRow


def _sanitize_var(name: str) -> str:
    """Turn a filename into a safe python identifier for the dataframe variable."""
    stem = Path(name or "").stem
    var = re.sub(r"\W+", "_", stem).strip("_").lower()
    if not var or var[0].isdigit():
        var = f"df_{var}" if var else "df"
    return var


def _link_session_datasets(session_id: str, dataset_ids: list[str]) -> None:
    """Link every requested dataset to the session (Phase 3 multi-source).

    Guarded: before the multi-data slice lands (or on the single-file path) this
    is a no-op so existing behaviour is preserved exactly.
    """
    try:
        from datasets.store import link_dataset_to_session, get_dataset_meta
    except Exception:  # multi-data slice not present yet
        return
    for i, did in enumerate(dataset_ids):
        if i == 0:
            var = "df"
        else:
            try:
                meta = get_dataset_meta(did)
            except Exception:
                meta = None
            var = _sanitize_var(meta["filename"]) if meta else f"df_{i}"
        try:
            link_dataset_to_session(session_id, did, var)
        except Exception:
            # Never fail the run on a link problem — prepare falls back to single.
            continue


def _load_conversation(session, session_id: str) -> list:
    """Prior turns for the session as [{role, content}], oldest-first (text only)."""
    rows = (
        session.query(MessageRow)
        .filter(MessageRow.session_id == session_id)
        .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in rows]


def run_agent(
    dataset_id: str,
    question: str,
    session_id: str | None = None,
    dataset_ids: list[str] | None = None,
    clarification_answer: str | None = None,
) -> str:
    """Run one analysis question end-to-end. Returns the run_id.

    Phase 3: ``dataset_ids`` lists every dataset to load into the session (for a
    cross-file join/compare); it defaults to ``[dataset_id]``. ``clarification_answer``
    is the user's reply to a prior clarifying question — when set it forces the
    agent to write code rather than clarify again.

    Reads the persisted RunRow for status/answer; on a failed run the row has
    status="failed" and answer_text is None (never a fabricated number). On a
    clarification the row has status="needs_clarification" and no answer.
    """
    ids = [i for i in (dataset_ids or [dataset_id]) if i]

    with create_db_session() as session:
        if session_id is None:
            sess = SessionRow(dataset_id=dataset_id, total_tokens=0)
            session.add(sess)
            session.flush()
            session_id = sess.id
            conversation: list = []
        else:
            conversation = _load_conversation(session, session_id)

        run = RunRow(
            dataset_id=dataset_id,
            question=question,
            status="pending",
            session_id=session_id,
        )
        session.add(run)
        session.flush()
        run_id = run.id

    _link_session_datasets(session_id, ids)

    initial: AgentState = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "session_id": session_id,
        "question": question,
        "conversation": conversation,
        "clarification_answer": clarification_answer,
        "max_steps": get_settings().max_steps,
        "error": None,
    }
    final_state = compiled_graph.invoke(initial)

    _persist_turn(run_id, session_id, question, final_state)
    return run_id


def _persist_turn(run_id: str, session_id: str, question: str, state: dict) -> None:
    """Append the user (+ assistant) turns and accumulate the session's tokens.

    On a ``needs_clarification`` run only the user turn is recorded — NEVER a
    fabricated assistant answer.
    """
    tokens = state.get("tokens") or {}
    run_total = int(tokens.get("total") or 0)
    needs_clarification = state.get("status") == "needs_clarification"

    with create_db_session() as session:
        session.add(
            MessageRow(session_id=session_id, run_id=run_id, role="user", content=question)
        )
        if not needs_clarification:
            answer_text = state.get("answer") or ""
            if not answer_text and state.get("error"):
                # Failed run: record a brief assistant note so the conversation
                # stays coherent, but never a fabricated number.
                answer_text = f"(no answer — {state.get('error')})"
            session.add(
                MessageRow(
                    session_id=session_id, run_id=run_id, role="assistant", content=answer_text
                )
            )
        sess = session.get(SessionRow, session_id)
        if sess is not None:
            sess.total_tokens = int(sess.total_tokens or 0) + run_total
