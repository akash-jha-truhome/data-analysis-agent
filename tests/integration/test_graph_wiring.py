"""Deterministic graph <-> REAL sandbox <-> DB wiring test.

WHY THIS EXISTS (and why it patches the LLM):
The authoritative end-to-end test — ``tests/test_agent_e2e.py`` — hits REAL
Gemini Flash and is the source of truth for the code-execution loop. In THIS
build environment, egress to ``generativelanguage.googleapis.com`` is blocked by
a corporate proxy (Zscaler returns 403 "AI/ML site blocked"), so the real call
cannot complete here. To still prove the rest of the slice wiring end-to-end —
``prepare -> write_code -> execute (REAL subprocess sandbox over the FULL 60k-row
parquet) -> answer -> build_chart -> finalize -> SQLite`` — this test substitutes
ONLY the two Gemini calls with canned outputs. Everything else is real: the real
sandbox subprocess, the real parquet, the real DB, the real chart builder.

This is NOT a substitute for the real-key e2e; it is a wiring check that runs
where Gemini egress is blocked.
"""
import io

import pandas as pd
import pytest

from graph.runner import run_agent


_WRITE_CODE = "```python\nresult = df.groupby('region')['revenue'].sum().reset_index()\n```"
_ANSWER_JSON = (
    '{"answer": "North has the highest total revenue.",'
    ' "key_numbers": [{"label": "North", "value": 0}],'
    ' "chart": {"type": "bar", "x": "region", "y": "revenue", "series": null}}'
)


@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    import datasets.store as store_module
    import observability.audit_log as audit_module

    root = tmp_path / "data"
    monkeypatch.setattr(store_module, "_data_root", lambda: root)
    monkeypatch.setattr(audit_module, "_data_root", lambda: root)
    return root


@pytest.fixture()
def canned_llm(monkeypatch):
    """Patch ONLY the LLM (Gemini egress is blocked here) — sandbox stays real."""
    import llm.client as client_module

    def fake_call_with_usage(self, prompt, *, system=None):
        usage = {"prompt": 100, "completion": 20, "total": 120}
        # Distinguish the two Gemini calls by the answer prompt's unique phrase
        # (robust; both prompts mention JSON now that write_code has a clarify path).
        if system and "explains a COMPUTED result" in system:
            return _ANSWER_JSON, usage
        return _WRITE_CODE, usage

    monkeypatch.setattr(client_module.LLMClient, "call_with_usage", fake_call_with_usage)


def test_full_loop_computes_true_full_data_aggregate_via_real_sandbox(data_root, canned_llm):
    import db.session as session_module
    from sqlalchemy.orm import Session
    from db.models import RunRow
    from datasets.store import store_dataset

    n = 60_000
    regions = ["North"] * 5 + [["North", "South", "East"][i % 3] for i in range(n - 5)]
    revenue = [1.0] * 5 + [1000.0] * (n - 5)
    df = pd.DataFrame({"region": regions, "revenue": revenue})
    expected_total = float(df["revenue"].sum())        # ~59,995,005
    assert float(df.head(5)["revenue"].sum()) == 5.0    # sample is unrepresentative

    csv = data_root / "sales.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv, index=False)
    meta = store_dataset(file_path=csv, filename="sales.csv")

    run_id = run_agent(meta["dataset_id"], "total revenue by region")

    with Session(session_module._engine) as s:
        row = s.get(RunRow, run_id)

    assert row.status == "completed"
    assert row.generated_code and "groupby" in row.generated_code

    # The REAL sandbox computed over ALL 60k rows, not the 5 samples.
    import json
    table = json.loads(row.result_json)
    total = sum(float(r[1]) for r in table["rows"])
    assert abs(total - expected_total) < 1.0, (total, expected_total)

    # Chart + tokens + trace persisted.
    assert row.chart_json and json.loads(row.chart_json)["data"]
    assert row.total_tokens == 240  # 2 canned LLM calls * 120
    steps = json.loads(row.step_trace_json)
    assert any(st["action"] == "execute" and st["ok"] for st in steps)
