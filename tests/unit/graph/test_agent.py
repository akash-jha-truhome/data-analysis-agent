"""Graph structure + pure-node unit tests (no LLM, no env vars required)."""
import json

import pandas as pd

from graph.edges import route_after_execute
from graph.nodes import (
    build_write_code_prompt,
    extract_code,
    extract_json,
    handle_error,
)
from datasets.loader import profile_dataframe


def test_graph_compiles():
    """Compiled graph builds without requiring any env vars."""
    from graph.agent import compiled_graph, agentic_ai

    assert compiled_graph is not None
    assert agentic_ai is compiled_graph
    nodes = set(compiled_graph.get_graph().nodes)
    for name in ("prepare", "write_code", "execute", "answer", "build_chart", "finalize", "handle_error"):
        assert name in nodes


def test_route_after_execute_ok_goes_to_answer():
    state = {"exec_result": {"ok": True}, "attempt": 1, "max_steps": 3}
    assert route_after_execute(state) == "answer"


def test_route_after_execute_code_error_retries_while_under_max():
    state = {"exec_result": {"ok": False}, "attempt": 1, "max_steps": 3}
    assert route_after_execute(state) == "write_code"


def test_route_after_execute_exhausted_goes_to_handle_error():
    state = {"exec_result": {"ok": False}, "attempt": 3, "max_steps": 3}
    assert route_after_execute(state) == "handle_error"


def test_route_after_execute_infra_error_is_fatal():
    state = {"error": "sandbox died", "exec_result": {"ok": False}, "attempt": 1, "max_steps": 3}
    assert route_after_execute(state) == "handle_error"


def test_extract_code_from_fenced_block():
    text = "Plan: sum it.\n```python\nresult = df['x'].sum()\n```\n"
    assert extract_code(text) == "result = df['x'].sum()"


def test_extract_json_tolerates_fence_and_prose():
    text = 'Here you go:\n```json\n{"answer": "hi", "key_numbers": [], "chart": {}}\n```'
    parsed = extract_json(text)
    assert parsed["answer"] == "hi"


def test_write_code_prompt_contains_only_sample_rows_never_full_data():
    """CRITICAL: the write_code prompt must carry <= sample_rows rows, never the full df."""
    n = 60_000
    sentinel = 424242.123  # a value that appears ONLY outside the sample head
    df = pd.DataFrame({"region": ["A"] * n, "revenue": [1.0] * n})
    df.loc[100, "revenue"] = sentinel  # row 100 is NOT in the first-5 head

    profile = profile_dataframe(df, sample_rows=5)
    schema = {"columns": profile["columns"], "n_rows": profile["n_rows"], "n_cols": profile["n_cols"]}

    prompt = build_write_code_prompt(schema, profile["sample_rows"], "total revenue by region")

    # Exactly the sample rows are embedded — no more.
    assert len(profile["sample_rows"]) == 5
    embedded = json.loads(prompt[prompt.index("["):prompt.index("]") + 1])
    assert len(embedded) == 5
    # The full-data-only sentinel must never reach the LLM prompt.
    assert str(sentinel) not in prompt
    # Schema (row count) is fine to include; raw data beyond the sample is not.
    assert "60000" in prompt  # n_rows metadata is allowed


def test_write_code_retry_prompt_includes_prior_code_and_traceback():
    schema = {"columns": [{"name": "x", "dtype": "int64"}], "n_rows": 3, "n_cols": 1}
    prompt = build_write_code_prompt(
        schema, [{"x": 1}], "sum x",
        prior_code="result = df['nope'].sum()",
        traceback="KeyError: 'nope'",
    )
    assert "KeyError: 'nope'" in prompt
    assert "result = df['nope'].sum()" in prompt


def test_handle_error_never_fabricates_an_answer(_isolated_db):
    """A failed run must set status=failed and leave answer/key_numbers empty."""
    from sqlalchemy.orm import Session
    from db.models import RunRow
    import db.session as session_module

    with Session(session_module._engine) as s:
        row = RunRow(dataset_id="d1", question="impossible", status="pending")
        s.add(row)
        s.commit()
        run_id = row.id

    state = {
        "run_id": run_id,
        "dataset_id": "d1",
        "question": "impossible",
        "error": "code failed after max_steps",
        "step_trace": [{"step": 1, "action": "execute", "ok": False}],
        "tokens": {"prompt": 10, "completion": 0, "total": 10},
    }
    out = handle_error(state)
    assert out["status"] == "failed"
    assert "answer" not in out or out.get("answer") is None

    with Session(session_module._engine) as s:
        persisted = s.get(RunRow, run_id)
    assert persisted.status == "failed"
    assert persisted.answer_text is None            # NO fabricated answer
    assert persisted.key_numbers_json is None        # NO fabricated numbers
    assert persisted.error_message == "code failed after max_steps"
