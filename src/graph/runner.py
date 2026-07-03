"""Runner: create a pending RunRow, invoke the graph, return the run_id.

The graph's ``finalize`` / ``handle_error`` nodes persist the final state onto
the same RunRow, so callers read the row (or use GET /runs/{id}) for the result.
"""
from graph.agent import compiled_graph
from graph.state import AgentState
from config.settings import get_settings
from db.session import create_db_session
from db.models import RunRow


def run_agent(dataset_id: str, question: str) -> str:
    """Run one analysis question end-to-end. Returns the run_id.

    Reads the persisted RunRow for status/answer; on a failed run the row has
    status="failed" and answer_text is None (never a fabricated number).
    """
    with create_db_session() as session:
        run = RunRow(dataset_id=dataset_id, question=question, status="pending")
        session.add(run)
        session.flush()
        run_id = run.id

    initial: AgentState = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "max_steps": get_settings().max_steps,
        "error": None,
    }
    compiled_graph.invoke(initial)
    return run_id
