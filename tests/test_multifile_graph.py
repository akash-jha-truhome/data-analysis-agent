"""Phase 3 — multi-dataframe execution + multi-schema prompt (slice-multi-graph).

Layers:
  a. Sandbox multi-df (REAL child process, no LLM) — two named parquet files are
     both loaded and a join across them runs.
  b. Multi-schema write_code prompt (pure fn, no LLM) — each dataset is rendered
     with ITS variable name + schema + <=5 sample rows and no full-data dump.
  c. Real-Gemini cross-file e2e — SKIPS without a key (never stubs).
"""
import io

import pandas as pd
import pytest

from config.settings import get_settings


# --------------------------------------------------------------------------- #
# a. Sandbox multi-df — real subprocess, two dataframes available by name
# --------------------------------------------------------------------------- #

def test_sandbox_loads_two_dataframes_and_joins_them(tmp_path):
    from sandbox.executor import run_code

    a = pd.DataFrame({"k": [1, 2, 3], "left": [10, 20, 30]})
    b = pd.DataFrame({"k": [1, 2, 3], "right": [100, 200, 300]})
    a_path = tmp_path / "a.parquet"
    b_path = tmp_path / "b.parquet"
    a.to_parquet(a_path)
    b.to_parquet(b_path)

    code = "result = a.merge(b, on='k')"
    out = run_code(
        code,
        {"a": str(a_path), "b": str(b_path)},
        timeout_s=25,
        mem_mb=2048,
    )

    assert out["ok"] is True, out
    table = out["result_table"]
    assert set(table["columns"]) == {"k", "left", "right"}
    by_k = {row[table["columns"].index("k")]: row for row in table["rows"]}
    # k=2 joins left=20 with right=200
    r = by_k[2]
    assert r[table["columns"].index("left")] == 20
    assert r[table["columns"].index("right")] == 200


def test_sandbox_missing_named_dataframe_is_a_code_error_not_infra(tmp_path):
    """Referencing an unloaded frame is a normal code error (ok=False), the loop
    can retry — it does NOT crash the sandbox."""
    from sandbox.executor import run_code

    a = pd.DataFrame({"k": [1, 2]})
    a_path = tmp_path / "a.parquet"
    a.to_parquet(a_path)

    out = run_code(
        "result = a.merge(missing, on='k')",
        {"a": str(a_path)},
        timeout_s=25,
        mem_mb=2048,
    )
    assert out["ok"] is False
    assert "missing" in (out["error"] or "") or "NameError" in (out["traceback"] or "")


# --------------------------------------------------------------------------- #
# b. Multi-schema prompt — both variable names + schemas, no full-data dump
# --------------------------------------------------------------------------- #

_FULL_DATA_SENTINEL = "__FULL_DATA_ROW__"


def _dataset(var_name: str, note_col: str) -> dict:
    sample_rows = [
        {"k": i, note_col: _FULL_DATA_SENTINEL} for i in range(5)
    ]
    schema = {
        "columns": [
            {"name": "k", "dtype": "int64"},
            {"name": note_col, "dtype": "object"},
        ],
        "n_rows": 250_000,
        "n_cols": 2,
    }
    return {"var_name": var_name, "schema": schema, "sample_rows": sample_rows}


def test_multi_schema_prompt_renders_each_dataset_by_name_no_full_data():
    from graph.nodes import build_write_code_prompt

    datasets = [_dataset("orders", "onote"), _dataset("customers", "cnote")]
    prompt = build_write_code_prompt(
        schema={},
        sample_rows=[],
        question="join orders with customers on k",
        datasets=datasets,
    )

    # Both variable names + schemas rendered.
    assert "`orders`" in prompt
    assert "`customers`" in prompt
    assert "onote" in prompt and "cnote" in prompt
    assert "250000 rows" in prompt or "250000" in prompt

    # CRITICAL: only <=5 sample rows PER dataset — never the full 250k dump.
    # 5 rows x 2 datasets => at most 10 sentinel occurrences.
    assert prompt.count(_FULL_DATA_SENTINEL) <= 10


def test_single_dataset_prompt_unchanged_backward_compat():
    """A single dataset (var `df`) renders exactly as Phase 1/2 did."""
    from graph.nodes import build_write_code_prompt

    schema = {
        "columns": [{"name": "region", "dtype": "object"}, {"name": "revenue", "dtype": "int64"}],
        "n_rows": 100,
        "n_cols": 2,
    }
    sample_rows = [{"region": "N", "revenue": 1}]
    prompt = build_write_code_prompt(schema, sample_rows, "total revenue")
    assert "Dataset schema" in prompt
    assert "`orders`" not in prompt  # no multi-source framing for a single df
    assert "Question: total revenue" in prompt

    # A single-element datasets list also renders the single-df path (var df).
    prompt2 = build_write_code_prompt(
        schema, sample_rows, "total revenue",
        datasets=[{"var_name": "df", "schema": schema, "sample_rows": sample_rows}],
    )
    assert "Dataset schema" in prompt2
    assert "Multiple datasets" not in prompt2


# --------------------------------------------------------------------------- #
# c. Real-Gemini cross-file e2e — SKIPS without a key (never stubs)
# --------------------------------------------------------------------------- #

def _gemini_ready() -> bool:
    return bool(get_settings().gemini_api_key)


requires_gemini = pytest.mark.skipif(
    not _gemini_ready(),
    reason="AGENT_GEMINI_API_KEY not set in .env (Zscaler blocks live Gemini here)",
)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    import datasets.store as store_module
    import observability.audit_log as audit_module

    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    monkeypatch.setattr(audit_module, "_data_root", lambda: root)
    return root


@requires_gemini
def test_real_gemini_cross_file_join_computes_across_both(api_client, data_root):
    """Two related CSVs in one session; a cross-file question is answered by
    executed pandas over BOTH frames. The expected number is verified with pandas."""
    orders = pd.DataFrame(
        {"customer_id": [1, 2, 1, 3, 2], "amount": [100.0, 50.0, 25.0, 75.0, 30.0]}
    )
    customers = pd.DataFrame(
        {"customer_id": [1, 2, 3], "region": ["North", "South", "North"]}
    )
    # Ground truth: total amount by region computed with a real pandas join.
    merged = orders.merge(customers, on="customer_id")
    expected = merged.groupby("region")["amount"].sum().to_dict()

    up1 = api_client.post(
        "/datasets",
        files={"file": ("orders.csv", io.BytesIO(orders.to_csv(index=False).encode()), "text/csv")},
    )
    up2 = api_client.post(
        "/datasets",
        files={"file": ("customers.csv", io.BytesIO(customers.to_csv(index=False).encode()), "text/csv")},
    )
    assert up1.status_code == 200 and up2.status_code == 200
    oid = up1.json()["data"]["dataset_id"]
    cid = up2.json()["data"]["dataset_id"]

    r = api_client.post(
        "/ask",
        json={
            "dataset_id": oid,
            "dataset_ids": [oid, cid],
            "question": "total amount by region, joining orders to customers on customer_id",
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "completed", d
    table = d["table"]
    assert table and table["rows"]
    # Verify the computed totals match the pandas ground truth for both regions.
    cols = table["columns"]
    region_i = next(i for i, c in enumerate(cols) if "region" in c.lower())
    amount_i = next(i for i in range(len(cols)) if i != region_i)
    got = {row[region_i]: float(row[amount_i]) for row in table["rows"]}
    for region, total in expected.items():
        assert region in got
        assert abs(got[region] - total) < 0.01, (region, got[region], total)


@requires_gemini
def test_real_gemini_ambiguous_question_triggers_clarification(api_client, data_root):
    """A genuinely ambiguous question (two plausible numeric metrics, unclear which)
    makes the agent ask ONE clarifying question rather than guess."""
    df = pd.DataFrame(
        {
            "product": (["A", "B", "C"] * 40)[:120],
            "revenue": [float(i % 50) for i in range(120)],
            "profit": [float(i % 7) for i in range(120)],
        }
    )
    up = api_client.post(
        "/datasets",
        files={"file": ("sales.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")},
    )
    assert up.status_code == 200
    dataset_id = up.json()["data"]["dataset_id"]

    r = api_client.post(
        "/ask",
        json={"dataset_id": dataset_id, "question": "which product is best?"},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "needs_clarification", d
    assert d["needs_clarification"] is True
    assert d["clarification"], "a clarifying question must be surfaced"
    assert d["answer"] is None  # NEVER a fabricated answer

    # Resume: answering the clarification forces a computed answer.
    r2 = api_client.post(
        "/ask",
        json={
            "dataset_id": dataset_id,
            "question": "which product is best?",
            "session_id": d["session_id"],
            "clarification_answer": "by total revenue",
        },
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()["data"]
    assert d2["status"] == "completed", d2
    assert d2["answer"]
