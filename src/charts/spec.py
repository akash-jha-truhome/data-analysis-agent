"""Deterministic Plotly figure-spec builder.

Builds a Plotly ``{"data": [...], "layout": {...}}`` figure spec from the
``answer`` node's chart hint (``{type, x, y, series}``) plus the computed
``result_table`` (``{columns, rows}``). No LLM, no second data pass — the chart
is assembled purely from the already-computed table.

If the result shape cannot be charted (e.g. a single scalar, or the hinted
columns are missing), it degrades to a table-only spec so the run still
completes with the prose answer + table. The chart is optional; the answer is
not.
"""
from __future__ import annotations

from typing import Any

_VALID_TYPES = {"bar", "line", "scatter", "pie"}


def _column_index(columns: list[str], name: Any) -> int | None:
    if name is None:
        return None
    try:
        return columns.index(name)
    except (ValueError, TypeError):
        return None


def _col_values(rows: list[list], idx: int) -> list:
    return [r[idx] if idx < len(r) else None for r in rows]


def _is_numeric_column(rows: list[list], idx: int) -> bool:
    """True if the column has at least one numeric (non-bool) value."""
    for r in rows:
        if idx < len(r):
            v = r[idx]
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                return True
    return False


def _first_numeric_column(rows: list[list], *, exclude: int, ncols: int) -> int | None:
    for idx in range(ncols):
        if idx == exclude:
            continue
        if _is_numeric_column(rows, idx):
            return idx
    return None


def _table_only(title: str, note: str = "This result is shown as a table.") -> dict:
    return {
        "data": [],
        "layout": {"title": title, "annotations": [{"text": note, "showarrow": False}]},
        "table_only": True,
    }


def build_chart_spec(chart_hint: dict | None, result_table: dict | None) -> dict:
    """Return a Plotly figure spec, or a table-only spec when un-chartable."""
    title = "Result"
    if not result_table or not result_table.get("columns") or not result_table.get("rows"):
        # Scalar / empty result — nothing to chart.
        return _table_only(title)

    columns: list[str] = list(result_table["columns"])
    rows: list[list] = list(result_table["rows"])
    hint = chart_hint or {}

    ctype = hint.get("type")
    if ctype not in _VALID_TYPES:
        ctype = "bar"

    x_idx = _column_index(columns, hint.get("x"))
    y_idx = _column_index(columns, hint.get("y"))

    # Sensible defaults when the hint omitted/mismatched columns: first column
    # is the axis/category, and the value is the first NUMERIC column (a text
    # column on the y-axis renders as a blank chart).
    if x_idx is None:
        x_idx = 0
    if y_idx is None or y_idx == x_idx or not _is_numeric_column(rows, y_idx):
        y_idx = _first_numeric_column(rows, exclude=x_idx, ncols=len(columns))
        if y_idx is None and len(columns) > 1:
            y_idx = 1 if x_idx != 1 else 0

    if y_idx is None:
        # Only one column — cannot form an (x, y) chart.
        return _table_only(title)

    x_vals = _col_values(rows, x_idx)
    y_vals = _col_values(rows, y_idx)
    x_name = columns[x_idx]
    y_name = columns[y_idx]
    series_idx = _column_index(columns, hint.get("series"))

    title = f"{y_name} by {x_name}"

    if ctype == "pie":
        trace = {"type": "pie", "labels": x_vals, "values": y_vals}
        return {"data": [trace], "layout": {"title": title}}

    if ctype == "scatter":
        trace = {"type": "scatter", "mode": "markers", "x": x_vals, "y": y_vals, "name": y_name}
    elif ctype == "line":
        trace = {"type": "scatter", "mode": "lines+markers", "x": x_vals, "y": y_vals, "name": y_name}
    else:  # bar
        trace = {"type": "bar", "x": x_vals, "y": y_vals, "name": y_name}

    layout = {"title": title, "xaxis": {"title": x_name}, "yaxis": {"title": y_name}}

    # Grouped series -> split into one trace per series value.
    if series_idx is not None and series_idx not in (x_idx, y_idx):
        series_vals = _col_values(rows, series_idx)
        groups: dict[Any, dict[str, list]] = {}
        for xv, yv, sv in zip(x_vals, y_vals, series_vals):
            g = groups.setdefault(sv, {"x": [], "y": []})
            g["x"].append(xv)
            g["y"].append(yv)
        data = []
        for sv, g in groups.items():
            t = dict(trace)
            t["x"], t["y"], t["name"] = g["x"], g["y"], str(sv)
            data.append(t)
        return {"data": data, "layout": layout}

    return {"data": [trace], "layout": layout}
