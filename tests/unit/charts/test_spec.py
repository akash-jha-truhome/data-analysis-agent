"""Deterministic Plotly figure-spec builder tests (no LLM)."""
from charts.spec import build_chart_spec


_TABLE = {"columns": ["region", "revenue"], "rows": [["West", 1200.0], ["East", 980.0]]}


def test_bar_spec_bars_equal_table_values():
    spec = build_chart_spec({"type": "bar", "x": "region", "y": "revenue"}, _TABLE)
    trace = spec["data"][0]
    assert trace["type"] == "bar"
    assert trace["x"] == ["West", "East"]
    assert trace["y"] == [1200.0, 980.0]


def test_line_spec_for_time_series():
    table = {"columns": ["month", "sales"], "rows": [["Jan", 10], ["Feb", 20], ["Mar", 15]]}
    spec = build_chart_spec({"type": "line", "x": "month", "y": "sales"}, table)
    trace = spec["data"][0]
    assert trace["type"] == "scatter"
    assert "lines" in trace["mode"]
    assert trace["y"] == [10, 20, 15]


def test_scatter_spec_for_two_measures():
    table = {"columns": ["ad_spend", "revenue"], "rows": [[100, 500], [200, 900]]}
    spec = build_chart_spec({"type": "scatter", "x": "ad_spend", "y": "revenue"}, table)
    assert spec["data"][0]["type"] == "scatter"
    assert spec["data"][0]["mode"] == "markers"


def test_pie_spec_uses_labels_and_values():
    spec = build_chart_spec({"type": "pie", "x": "region", "y": "revenue"}, _TABLE)
    trace = spec["data"][0]
    assert trace["type"] == "pie"
    assert trace["labels"] == ["West", "East"]
    assert trace["values"] == [1200.0, 980.0]


def test_scalar_result_degrades_to_table_only():
    # Un-chartable: a single scalar value / no result table.
    spec = build_chart_spec({"type": "bar"}, None)
    assert spec["table_only"] is True
    assert spec["data"] == []


def test_single_column_result_degrades_to_table_only():
    table = {"columns": ["total"], "rows": [[42.0]]}
    spec = build_chart_spec({"type": "bar"}, table)
    assert spec["table_only"] is True


def test_bad_hint_falls_back_to_first_two_columns():
    # Hint references columns that don't exist -> defaults, still charts.
    spec = build_chart_spec({"type": "bar", "x": "nope", "y": "also_nope"}, _TABLE)
    trace = spec["data"][0]
    assert trace["x"] == ["West", "East"]
    assert trace["y"] == [1200.0, 980.0]


def test_grouped_series_splits_into_multiple_traces():
    table = {
        "columns": ["month", "sales", "region"],
        "rows": [["Jan", 10, "W"], ["Jan", 5, "E"], ["Feb", 20, "W"], ["Feb", 8, "E"]],
    }
    spec = build_chart_spec({"type": "bar", "x": "month", "y": "sales", "series": "region"}, table)
    names = sorted(t["name"] for t in spec["data"])
    assert names == ["E", "W"]
