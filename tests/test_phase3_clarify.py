"""Phase 3 — clarification gate wiring (canned, CLEARLY-LABELLED Gemini stubs).

This is a WIRING test of the clarify decision folded into write_code + the
resume protocol — NOT the acceptance gate. The real-Gemini clarification path is
the skip-gated e2e in ``tests/test_multifile_graph.py``.

The clarify decision costs NO extra LLM call: write_code returns EITHER a
``{"clarify": ...}`` request OR code. When the user later answers, the same node
is forced to write code.
"""
import io

import pandas as pd
import pytest


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    import datasets.store as store_module
    import observability.audit_log as audit_module

    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    monkeypatch.setattr(audit_module, "_data_root", lambda: root)
    return root


@pytest.fixture(autouse=True)
def _clear_quality_cache():
    import graph.nodes as nodes
    nodes._QUALITY_CACHE.clear()
    yield
    nodes._QUALITY_CACHE.clear()


_CLARIFY = '{"clarify": "Which year did you mean, 2023 or 2024?"}'
_CODE = "```python\nresult = df['revenue'].sum()\n```"
_ANSWER = (
    '{"answer": "CANNED total is 60.", '
    '"key_numbers": [{"label": "total", "value": 60}], '
    '"chart": {"type": "bar", "x": null, "y": null, "series": null}, '
    '"suggestions": ["Break down by region?"]}'
)


@pytest.fixture()
def canned_gemini(monkeypatch):
    """write_code returns a clarify request UNLESS the user has clarified (the
    prompt then contains 'The user clarified'); answer returns canned JSON."""
    import graph.nodes as nodes

    calls = {"prompts": []}

    def _fake_call(self, prompt, *, system=None):
        calls["prompts"].append({"system": system, "prompt": prompt})
        usage = {"prompt": 5, "completion": 3, "total": 8}
        if "explains a COMPUTED result" in (system or ""):
            return _ANSWER, usage
        # write_code: clarify on first ask, code once clarified.
        if "The user clarified" in prompt:
            return _CODE, usage
        return _CLARIFY, usage

    monkeypatch.setattr(nodes.LLMClient, "call_with_usage", _fake_call)
    return calls


@pytest.fixture()
def _fake_sandbox(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("sandbox.executor")

    def _run(code, parquet_paths, *, timeout_s, mem_mb):
        return {
            "ok": True,
            "result_table": {"columns": ["revenue"], "rows": [[60]]},
            "result_repr": "60",
            "stdout": "",
            "error": None,
            "traceback": None,
            "duration_ms": 1,
        }

    fake.run_code = _run
    monkeypatch.setitem(sys.modules, "sandbox.executor", fake)
    return fake


def _store_tiny(data_root):
    from datasets.store import store_dataset

    df = pd.DataFrame({"region": ["N", "S", "E"], "revenue": [10, 20, 30]})
    csv = data_root / "tiny.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv, index=False)
    return store_dataset(file_path=csv, filename="tiny.csv")


def test_extract_clarify_detects_json_but_ignores_code():
    from graph.nodes import extract_clarify

    assert extract_clarify('{"clarify": "which year?"}') == "which year?"
    assert extract_clarify('```json\n{"clarify": "which metric?"}\n```') == "which metric?"
    # A code block is NEVER a clarify, even if it mentions a dict.
    assert extract_clarify("```python\nresult = {'clarify': df}\n```") is None
    # Plain prose / non-JSON is not a clarify.
    assert extract_clarify("Plan: sum revenue.") is None


# --------------------------------------------------------------------------- #
# Clarification wiring — first ask clarifies, resume computes
# --------------------------------------------------------------------------- #

def test_ambiguous_ask_sets_needs_clarification_and_persists_no_answer(
    data_root, canned_gemini, _fake_sandbox
):
    from graph.runner import run_agent
    from db.models import RunRow, MessageRow, SessionRow
    import db.session as session_module
    from sqlalchemy.orm import Session
    from domain.run import run_row_to_payload

    meta = _store_tiny(data_root)
    run_id = run_agent(meta["dataset_id"], "what were the sales?")

    with Session(session_module._engine) as s:
        row = s.get(RunRow, run_id)
        assert row.status == "needs_clarification"
        assert row.answer_text is None            # NO fabricated answer
        assert row.key_numbers_json is None       # NO fabricated numbers

        payload = run_row_to_payload(row)
        assert payload["needs_clarification"] is True
        assert payload["status"] == "needs_clarification"
        assert payload["clarification"] == "Which year did you mean, 2023 or 2024?"
        assert payload["answer"] is None

        # Only the user turn is recorded — no assistant answer.
        msgs = (
            s.query(MessageRow)
            .filter(MessageRow.session_id == row.session_id)
            .order_by(MessageRow.id.asc())
            .all()
        )
        assert [m.role for m in msgs] == ["user"]
        assert msgs[0].content == "what were the sales?"

        # Tokens from the single write_code call still accrue to the session.
        sess = s.get(SessionRow, row.session_id)
        assert sess.total_tokens == 8


def test_resume_with_clarification_answer_computes_and_completes(
    data_root, canned_gemini, _fake_sandbox
):
    from graph.runner import run_agent
    from db.models import RunRow
    import db.session as session_module
    from sqlalchemy.orm import Session

    meta = _store_tiny(data_root)
    first = run_agent(meta["dataset_id"], "what were the sales?")

    with Session(session_module._engine) as s:
        sid = s.get(RunRow, first).session_id

    # The user answers; the SAME question is re-issued WITH the clarification.
    second = run_agent(
        meta["dataset_id"],
        "what were the sales?",
        session_id=sid,
        clarification_answer="2024",
    )

    # The forced-code prompt carried the user's clarification.
    wc_prompts = [
        c["prompt"] for c in canned_gemini["prompts"]
        if "Dataset schema" in c["prompt"] and "The user clarified" in c["prompt"]
    ]
    assert wc_prompts, "resume must append the clarification to the write_code prompt"

    with Session(session_module._engine) as s:
        run2 = s.get(RunRow, second)
        assert run2.status == "completed"
        assert run2.answer_text == "CANNED total is 60."
        assert run2.session_id == sid


def test_ask_endpoint_returns_needs_clarification_as_200(
    api_client, data_root, canned_gemini, _fake_sandbox
):
    """POST /ask surfaces the clarifying question as a 200 (NOT an error) so the
    UI can prompt the user, then a resume with clarification_answer completes."""
    df = pd.DataFrame({"region": ["N", "S", "E"], "revenue": [10, 20, 30]})
    up = api_client.post(
        "/datasets",
        files={"file": ("t.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")},
    )
    assert up.status_code == 200
    dataset_id = up.json()["data"]["dataset_id"]

    r1 = api_client.post("/ask", json={"dataset_id": dataset_id, "question": "how did we do?"})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["status"] == "needs_clarification"
    assert d1["needs_clarification"] is True
    assert d1["clarification"] == "Which year did you mean, 2023 or 2024?"
    assert d1["answer"] is None

    r2 = api_client.post(
        "/ask",
        json={
            "dataset_id": dataset_id,
            "question": "how did we do?",
            "session_id": d1["session_id"],
            "clarification_answer": "2024",
        },
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()["data"]
    assert d2["status"] == "completed"
    assert d2["answer"] == "CANNED total is 60."
