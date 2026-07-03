"""End-to-end agent tests against REAL Gemini Flash.

These skip (never stub) when ``AGENT_GEMINI_API_KEY`` is absent. The happy-path
test runs the full HTTP -> graph -> sandbox -> Gemini loop over a 60k-row CSV
whose true aggregate is provably unreachable from the 5 sample rows shown to the
LLM. The error-path test drives the sandbox to fail repeatedly (real Gemini
write_code, monkeypatched executor) and asserts NO number is fabricated.
"""
import io
import sys
import types

import pandas as pd
import pytest

from config.settings import get_settings


def _gemini_ready() -> bool:
    return bool(get_settings().gemini_api_key)


requires_gemini = pytest.mark.skipif(not _gemini_ready(), reason="AGENT_GEMINI_API_KEY not set in .env")


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """Redirect dataset-store + audit-log writes into tmp."""
    import datasets.store as store_module
    import observability.audit_log as audit_module

    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    monkeypatch.setattr(audit_module, "_data_root", lambda: root)
    return root


def _big_skewed_csv() -> tuple[bytes, pd.DataFrame]:
    """60k rows. The head-5 sample is all region=North @ revenue=1.0, but the
    full data is dominated by 1000.0 values across regions. The true groupby-sum
    is therefore provably different from anything derivable from the 5 samples."""
    n = 60_000
    regions = ["North"] * 5 + [["North", "South", "East"][i % 3] for i in range(n - 5)]
    revenue = [1.0] * 5 + [1000.0] * (n - 5)
    df = pd.DataFrame({"region": regions, "revenue": revenue})
    return df.to_csv(index=False).encode(), df


@requires_gemini
def test_ask_computes_true_full_data_aggregate(api_client, data_root):
    csv_bytes, df = _big_skewed_csv()
    expected_total = float(df["revenue"].sum())        # ~59,995,005
    sample_sum = float(df.head(5)["revenue"].sum())    # == 5.0
    assert expected_total != sample_sum

    up = api_client.post("/datasets", files={"file": ("sales.csv", io.BytesIO(csv_bytes), "text/csv")})
    assert up.status_code == 200, up.text
    meta = up.json()["data"]
    assert meta["n_rows"] == 60_000
    dataset_id = meta["dataset_id"]

    r = api_client.post("/ask", json={"dataset_id": dataset_id, "question": "total revenue by region"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert data["status"] == "completed"

    # Real generated pandas ran.
    assert data["code"] and "df" in data["code"]

    # The computed table reflects the FULL dataset, not the 5 samples.
    table = data["table"]
    assert table and table["rows"]
    numeric_col = _numeric_column_index(table)
    total_from_table = sum(float(row[numeric_col]) for row in table["rows"])
    assert abs(total_from_table - expected_total) < 1.0, (total_from_table, expected_total)
    assert total_from_table > sample_sum * 1000  # nowhere near a sample-derived value

    # Key numbers are real full-data aggregates (each >> the sample max of 5).
    values = [_as_float(kn.get("value")) for kn in data["key_numbers"]]
    values = [v for v in values if v is not None]
    assert values and max(values) > 100.0

    # A chart spec was produced.
    assert data["chart"] is not None

    # Trace has entries; tokens were spent on the 2 (+retry) real LLM calls.
    assert data["steps"], "step_trace should not be empty"
    assert data["tokens"]["total"] > 0


@requires_gemini
def test_failed_run_never_fabricates_a_number(data_root, monkeypatch):
    """Sandbox errors repeatedly -> after max_steps the run is failed with a
    null answer and no key numbers. Real Gemini write_code, forced exec failure."""
    import config.settings as settings_module
    from datasets.store import store_dataset
    from graph.runner import run_agent
    from db.models import RunRow
    import db.session as session_module
    from sqlalchemy.orm import Session

    # Bound the loop tight so we make a single real Gemini call before failing.
    monkeypatch.setenv("AGENT_MAX_STEPS", "1")
    settings_module._settings = None

    # Force the sandbox to always report a code error (infra untouched).
    fake = types.ModuleType("sandbox.executor")

    def _always_fail(code, parquet_paths, *, timeout_s, mem_mb):
        return {
            "ok": False,
            "result_table": None,
            "result_repr": None,
            "stdout": "",
            "error": "KeyError: 'nonexistent'",
            "traceback": "Traceback...\nKeyError: 'nonexistent'",
            "duration_ms": 3,
        }

    fake.run_code = _always_fail
    monkeypatch.setitem(sys.modules, "sandbox.executor", fake)

    # A tiny real dataset to ask against.
    csv = data_root / "tiny.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(csv, index=False)
    meta = store_dataset(file_path=csv, filename="tiny.csv")

    # Unambiguous question (column `a` exists) so write_code produces real code
    # rather than triggering the Phase-3 clarification gate; the forced-fail
    # sandbox then drives the run to `failed` after retries.
    run_id = run_agent(meta["dataset_id"], "what is the sum of column a?")

    with Session(session_module._engine) as s:
        row = s.get(RunRow, run_id)

    assert row.status == "failed"
    assert row.answer_text is None          # NO fabricated answer
    assert row.key_numbers_json is None      # NO fabricated numbers
    assert row.error_message                 # a failure message is present
    assert (row.total_tokens or 0) > 0       # a real write_code LLM call happened


def _numeric_column_index(table: dict) -> int:
    for i, col in enumerate(table["columns"]):
        try:
            float(table["rows"][0][i])
            return i
        except (ValueError, TypeError):
            continue
    raise AssertionError("no numeric column in result table")


def _as_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
