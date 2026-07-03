"""Tests for the bounded, network-free pandas execution sandbox.

These run against real pandas in a real child process — no stubs.
"""
import json
import time

import numpy as np
import pandas as pd
import pytest

from sandbox.executor import run_code


@pytest.fixture
def df_parquet(tmp_path):
    """A small dataframe persisted to parquet, bound to variable name `df`."""
    df = pd.DataFrame(
        {
            "x": [1, 2, 3, 4],
            "group": ["a", "b", "a", "b"],
            "label": ["w", "x", "y", "z"],
        }
    )
    path = tmp_path / "data.parquet"
    df.to_parquet(path)
    return {"df": str(path)}


def _assert_json_serializable(result: dict) -> None:
    # Must round-trip through JSON with no custom encoder.
    json.dumps(result)


def test_happy_path_scalar_sum_returns_ok_and_correct_value(df_parquet):
    result = run_code(
        "result = df['x'].sum()",
        df_parquet,
        timeout_s=25,
        mem_mb=2048,
    )

    assert result["ok"] is True
    assert result["error"] is None
    assert result["traceback"] is None
    assert result["result_table"] == {"columns": ["value"], "rows": [[10]]}
    assert result["duration_ms"] >= 0
    _assert_json_serializable(result)


def test_groupby_dataframe_returns_correct_columns_and_rows(df_parquet):
    code = "result = df.groupby('group', as_index=False)['x'].sum()"
    result = run_code(code, df_parquet, timeout_s=25, mem_mb=2048)

    assert result["ok"] is True
    table = result["result_table"]
    assert table["columns"] == ["group", "x"]
    # group a: 1 + 3 = 4 ; group b: 2 + 4 = 6
    rows_by_group = {row[0]: row[1] for row in table["rows"]}
    assert rows_by_group == {"a": 4, "b": 6}
    _assert_json_serializable(result)


def test_series_result_becomes_two_column_index_value_table(df_parquet):
    code = "result = df.groupby('group')['x'].sum()"
    result = run_code(code, df_parquet, timeout_s=25, mem_mb=2048)

    assert result["ok"] is True
    table = result["result_table"]
    assert len(table["columns"]) == 2
    rows_by_group = {row[0]: row[1] for row in table["rows"]}
    assert rows_by_group == {"a": 4, "b": 6}
    _assert_json_serializable(result)


def test_bad_code_returns_error_and_traceback_without_raising(df_parquet):
    result = run_code(
        "result = df['nonexistent'].sum()",
        df_parquet,
        timeout_s=25,
        mem_mb=2048,
    )

    assert result["ok"] is False
    assert result["result_table"] is None
    assert result["error"]
    assert result["traceback"]
    assert "nonexistent" in result["traceback"]
    _assert_json_serializable(result)


def test_missing_result_assignment_returns_clear_error(df_parquet):
    result = run_code(
        "total = df['x'].sum()",
        df_parquet,
        timeout_s=25,
        mem_mb=2048,
    )

    assert result["ok"] is False
    assert result["result_table"] is None
    assert "result" in result["error"].lower()
    _assert_json_serializable(result)


def test_infinite_loop_is_bounded_by_timeout(df_parquet):
    start = time.monotonic()
    result = run_code(
        "while True:\n    pass",
        df_parquet,
        timeout_s=2,
        mem_mb=2048,
    )
    elapsed = time.monotonic() - start

    assert result["ok"] is False
    assert "timed out" in result["error"].lower()
    # The bound must actually work: return within a few seconds, not hang.
    assert elapsed < 10
    _assert_json_serializable(result)


def test_nan_numpy_and_timestamp_values_serialize_cleanly(tmp_path):
    df = pd.DataFrame(
        {
            "val": [1.5, np.nan, 3.0],
            "when": pd.to_datetime(["2024-01-01", "2024-06-15", "2024-12-31"]),
            "count": np.array([10, 20, 30], dtype="int64"),
        }
    )
    path = tmp_path / "data.parquet"
    df.to_parquet(path)

    result = run_code(
        "result = df",
        {"df": str(path)},
        timeout_s=25,
        mem_mb=2048,
    )

    assert result["ok"] is True
    _assert_json_serializable(result)

    table = result["result_table"]
    val_idx = table["columns"].index("val")
    when_idx = table["columns"].index("when")
    count_idx = table["columns"].index("count")

    # NaN -> None
    assert table["rows"][1][val_idx] is None
    # numpy int -> python int
    assert table["rows"][0][count_idx] == 10
    assert isinstance(table["rows"][0][count_idx], int)
    # timestamp -> iso string
    assert isinstance(table["rows"][0][when_idx], str)
    assert table["rows"][0][when_idx].startswith("2024-01-01")


def test_result_rows_are_capped(tmp_path):
    df = pd.DataFrame({"n": range(5000)})
    path = tmp_path / "big.parquet"
    df.to_parquet(path)

    result = run_code(
        "result = df",
        {"df": str(path)},
        timeout_s=25,
        mem_mb=2048,
    )

    assert result["ok"] is True
    assert len(result["result_table"]["rows"]) <= 1000
