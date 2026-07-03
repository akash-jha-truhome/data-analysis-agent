"""Phase 2 — conversation memory + deterministic data-quality profiling.

Layers:
  a. Data-quality (deterministic, real sandbox, NO Gemini) — fully local-green.
  b. Memory wiring (Gemini node calls monkeypatched with CLEARLY-LABELLED canned
     responses — a wiring test, NOT the acceptance gate).
  c. Prompt safety — the write_code prompt built with conversation history + a
     large df carries only <=5 sample rows and no full-data sentinel.
  d. Real-Gemini multi-turn e2e — SKIPS (never stubs) without a key.

All DB work runs against the isolated tmp SQLite from the autouse ``_isolated_db``
conftest fixture; the dataset store is redirected into tmp.
"""
import io

import pandas as pd
import pytest

from config.settings import get_settings


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """Redirect dataset-store + audit-log writes into tmp."""
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


# --------------------------------------------------------------------------- #
# a. Data-quality profiling — deterministic, real sandbox, no Gemini
# --------------------------------------------------------------------------- #

def test_profile_quality_flags_missing_duplicates_and_outliers(data_root):
    """A CSV with known missing values, duplicate rows, and a numeric outlier is
    profiled deterministically in the real sandbox — no LLM involved."""
    from datasets.store import store_dataset
    from graph.nodes import profile_quality

    # 10 base rows; `score` has a clear high outlier (9999) vs a ~10-50 cluster;
    # `age` has 2 missing; rows 0 and 1 are exact duplicates.
    df = pd.DataFrame(
        {
            "name": ["a", "a", "c", "d", "e", "f", "g", "h", "i", "j"],
            "age": [30, 30, None, 41, 25, None, 33, 29, 38, 45],
            "score": [10, 10, 20, 15, 30, 25, 40, 35, 22, 9999],
        }
    )
    csv = data_root / "dq.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv, index=False)
    meta = store_dataset(file_path=csv, filename="dq.csv")

    state = {
        "dataset_id": meta["dataset_id"],
        "parquet_paths": {"df": meta["parquet_path"]},
    }
    out = profile_quality(state)
    dq = out["data_quality"]

    # Missing: `age` reported with count 2.
    missing_cols = {m["column"]: m for m in dq["missing"]}
    assert "age" in missing_cols
    assert missing_cols["age"]["count"] == 2
    assert missing_cols["age"]["pct"] == pytest.approx(20.0, abs=0.01)

    # Duplicate row: rows 0 and 1 are identical -> exactly 1 duplicate.
    assert dq["duplicate_rows"] == 1

    # Outlier: `score` flagged.
    outlier_cols = {o["column"] for o in dq["outliers"]}
    assert "score" in outlier_cols

    assert dq["summary"] and dq["summary"] != "No data-quality issues detected."


def test_profile_quality_clean_data_reports_no_issues(data_root):
    from datasets.store import store_dataset
    from graph.nodes import profile_quality

    df = pd.DataFrame({"x": list(range(1, 21)), "y": [i * 2 for i in range(1, 21)]})
    csv = data_root / "clean.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv, index=False)
    meta = store_dataset(file_path=csv, filename="clean.csv")

    out = profile_quality(
        {"dataset_id": meta["dataset_id"], "parquet_paths": {"df": meta["parquet_path"]}}
    )
    dq = out["data_quality"]
    assert dq["missing"] == []
    assert dq["duplicate_rows"] == 0
    assert dq["outliers"] == []
    assert dq["summary"] == "No data-quality issues detected."


def test_profile_quality_never_fails_the_run_on_bad_path(data_root):
    """Missing parquet -> sandbox code error -> degrades to {} (never raises)."""
    from graph.nodes import profile_quality

    out = profile_quality(
        {"dataset_id": "ds-nope", "parquet_paths": {"df": "/no/such/file.parquet"}}
    )
    assert out["data_quality"] == {}


# --------------------------------------------------------------------------- #
# b. Memory wiring — canned (LABELLED) Gemini responses, NOT the gate
# --------------------------------------------------------------------------- #

_CANNED_CODE = "```python\nresult = df['revenue'].sum()\n```"
_CANNED_ANSWER = (
    '{"answer": "CANNED wiring-test answer.", '
    '"key_numbers": [{"label": "total", "value": 42}], '
    '"chart": {"type": "bar", "x": null, "y": null, "series": null}, '
    '"suggestions": ["Break it down by region?", "Show the monthly trend?"]}'
)


@pytest.fixture()
def canned_gemini(monkeypatch):
    """Monkeypatch the two Gemini node calls with CLEARLY-LABELLED canned text.

    This is a WIRING test — it exercises session/memory persistence, not the LLM.
    The real-Gemini acceptance path is the skip-gated e2e test below.
    """
    import graph.nodes as nodes

    calls = {"prompts": []}

    def _fake_call(self, prompt, *, system=None):
        calls["prompts"].append({"system": system, "prompt": prompt})
        usage = {"prompt": 5, "completion": 3, "total": 8}
        if "explains a COMPUTED result" in (system or ""):
            return _CANNED_ANSWER, usage
        return _CANNED_CODE, usage

    monkeypatch.setattr(nodes.LLMClient, "call_with_usage", _fake_call)
    return calls


@pytest.fixture()
def _fake_sandbox(monkeypatch):
    """profile_quality + execute both call run_code; return a benign scalar."""
    import sys
    import types

    fake = types.ModuleType("sandbox.executor")

    def _run(code, parquet_paths, *, timeout_s, mem_mb):
        return {
            "ok": True,
            "result_table": {"columns": ["revenue"], "rows": [[42]]},
            "result_repr": "42",
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


def test_first_turn_creates_session_and_messages(data_root, canned_gemini, _fake_sandbox):
    from graph.runner import run_agent
    from db.models import SessionRow, MessageRow, RunRow
    import db.session as session_module
    from sqlalchemy.orm import Session

    meta = _store_tiny(data_root)
    run_id = run_agent(meta["dataset_id"], "total revenue")

    with Session(session_module._engine) as s:
        run = s.get(RunRow, run_id)
        assert run.session_id is not None
        sid = run.session_id

        sess = s.get(SessionRow, sid)
        assert sess is not None
        assert sess.dataset_id == meta["dataset_id"]
        assert sess.total_tokens == 16  # write_code(8) + answer(8)

        msgs = (
            s.query(MessageRow)
            .filter(MessageRow.session_id == sid)
            .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
            .all()
        )
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[0].content == "total revenue"
        assert msgs[0].run_id == run_id
        assert "CANNED" in msgs[1].content


def test_second_turn_loads_prior_conversation_and_accumulates(
    data_root, canned_gemini, _fake_sandbox
):
    from graph.runner import run_agent
    from db.models import SessionRow, MessageRow, RunRow
    import db.session as session_module
    from sqlalchemy.orm import Session

    meta = _store_tiny(data_root)
    first_run = run_agent(meta["dataset_id"], "total revenue")

    with Session(session_module._engine) as s:
        sid = s.get(RunRow, first_run).session_id

    canned_gemini["prompts"].clear()
    second_run = run_agent(meta["dataset_id"], "and by region?", session_id=sid)

    # The write_code prompt on the follow-up carries the prior turn TEXT.
    wc_prompts = [
        c["prompt"] for c in canned_gemini["prompts"]
        if "Dataset schema" in c["prompt"]
    ]
    assert wc_prompts
    assert "Conversation so far" in wc_prompts[0]
    assert "total revenue" in wc_prompts[0]

    with Session(session_module._engine) as s:
        run2 = s.get(RunRow, second_run)
        assert run2.session_id == sid  # same session

        sess = s.get(SessionRow, sid)
        assert sess.total_tokens == 32  # two runs x 16

        msgs = (
            s.query(MessageRow)
            .filter(MessageRow.session_id == sid)
            .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
            .all()
        )
        # 2 turns x 2 messages, oldest first.
        assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]
        assert msgs[2].content == "and by region?"


def test_ask_endpoint_returns_session_and_insights(api_client, data_root, canned_gemini, _fake_sandbox):
    """POST /ask surfaces session_id + suggestions + data_quality in the payload,
    and a follow-up with that session_id reuses the session."""
    df = pd.DataFrame({"region": ["N", "S", "E"], "revenue": [10, 20, 30]})
    up = api_client.post(
        "/datasets",
        files={"file": ("t.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")},
    )
    assert up.status_code == 200, up.text
    dataset_id = up.json()["data"]["dataset_id"]

    r1 = api_client.post("/ask", json={"dataset_id": dataset_id, "question": "total revenue"})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["session_id"]
    assert d1["suggestions"] == ["Break it down by region?", "Show the monthly trend?"]
    assert d1["data_quality"] is not None  # profiled (sandbox faked, still a dict)

    sid = d1["session_id"]
    r2 = api_client.post(
        "/ask",
        json={"dataset_id": dataset_id, "question": "by region?", "session_id": sid},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["session_id"] == sid


# --------------------------------------------------------------------------- #
# c. Prompt safety — conversation history never leaks full data
# --------------------------------------------------------------------------- #

_FULL_DATA_SENTINEL = "__FULL_DATA_ROW__"


def test_write_code_prompt_with_history_carries_no_full_data():
    from graph.nodes import build_write_code_prompt

    # A large df: only <=5 sample rows must ever reach the prompt.
    sample_rows = [
        {"region": "N", "revenue": 1, "note": _FULL_DATA_SENTINEL} for _ in range(5)
    ]
    schema = {
        "columns": [
            {"name": "region", "dtype": "object"},
            {"name": "revenue", "dtype": "int64"},
            {"name": "note", "dtype": "object"},
        ],
        "n_rows": 100_000,
        "n_cols": 3,
    }
    conversation = [
        {"role": "user", "content": "total revenue"},
        {"role": "assistant", "content": "It was 60."},
    ]
    prompt = build_write_code_prompt(
        schema, sample_rows, "and by region?", conversation=conversation
    )

    # Conversation text is present.
    assert "Conversation so far" in prompt
    assert "total revenue" in prompt
    # Only the 5 sample rows carry the sentinel; a full-data dump (100k rows)
    # would contain far more than 5 occurrences.
    assert prompt.count(_FULL_DATA_SENTINEL) <= 5
    # The full row count is stated as schema metadata but the data is NOT dumped.
    assert "100000 rows" in prompt or "100000" in prompt


# --------------------------------------------------------------------------- #
# d. Real-Gemini multi-turn e2e — SKIPS without a key (never stubs)
# --------------------------------------------------------------------------- #

def _gemini_ready() -> bool:
    return bool(get_settings().gemini_api_key)


requires_gemini = pytest.mark.skipif(
    not _gemini_ready(), reason="AGENT_GEMINI_API_KEY not set in .env (Zscaler blocks live Gemini here)"
)


@requires_gemini
def test_multiturn_followup_resolves_against_prior_frame(api_client, data_root):
    """Q1 establishes a frame; a context-only follow-up (no dataset restated)
    must resolve against it, and suggestions must be non-empty."""
    df = pd.DataFrame(
        {
            "region": (["North", "South", "East"] * 400)[:1200],
            "revenue": [float(i % 100) for i in range(1200)],
        }
    )
    up = api_client.post(
        "/datasets",
        files={"file": ("sales.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")},
    )
    assert up.status_code == 200, up.text
    dataset_id = up.json()["data"]["dataset_id"]

    r1 = api_client.post(
        "/ask", json={"dataset_id": dataset_id, "question": "total revenue by region"}
    )
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["status"] == "completed"
    sid = d1["session_id"]
    assert sid
    assert d1["suggestions"], "answer must include non-empty follow-up suggestions"

    # Context-only follow-up: which region is highest? — needs the prior frame.
    r2 = api_client.post(
        "/ask",
        json={
            "dataset_id": dataset_id,
            "question": "which of those regions had the highest total?",
            "session_id": sid,
        },
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()["data"]
    assert d2["status"] == "completed"
    assert d2["session_id"] == sid
    assert d2["answer"] and any(
        reg.lower() in d2["answer"].lower() for reg in ("north", "south", "east")
    )
