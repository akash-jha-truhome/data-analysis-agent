"""CSV loading, profiling, and parquet normalization.

Pure functions over a pandas DataFrame. No DB or filesystem-store concerns
here — those live in ``datasets.store``.
"""
from __future__ import annotations

import keyword
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a CSV file into a DataFrame.

    Raises ValueError for an empty or unparseable CSV so the store/API layer
    can map it to a 400.
    """
    p = Path(path)
    try:
        df = pd.read_csv(p)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"CSV file is empty or has no columns: {p}") from exc
    except pd.errors.ParserError as exc:
        raise ValueError(f"CSV file could not be parsed: {p}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV file is not valid text: {p}") from exc

    if df.shape[1] == 0:
        raise ValueError(f"CSV file has no columns: {p}")
    return df


def load_excel(path: str | Path) -> dict[str, pd.DataFrame]:
    """Load every sheet of an Excel workbook into ``{sheet_name: DataFrame}``.

    Uses ``pd.read_excel(path, sheet_name=None)`` (openpyxl engine). Raises
    ValueError for an unreadable/empty workbook so the store/API layer can map
    it to a 400.
    """
    p = Path(path)
    try:
        sheets = pd.read_excel(p, sheet_name=None)
    except ValueError:
        raise
    except Exception as exc:  # openpyxl / xlrd parse failures
        raise ValueError(f"Excel file could not be parsed: {p}") from exc
    if not sheets:
        raise ValueError(f"Excel file has no sheets: {p}")
    return sheets


def sanitize_var_name(raw: str) -> str:
    """Derive a valid, lowercase python identifier from a filename/sheet name.

    Strips any file extension, lowercases, replaces runs of non-identifier
    characters with a single underscore, and guarantees the result is a valid,
    non-keyword identifier. Examples::

        "Orders 2024.csv" -> "orders_2024"
        "2020 data"       -> "col_2020_data"
        "class"           -> "class_"
        ""                -> "dataset"
    """
    text = str(raw or "").strip().lower()
    # Drop a trailing file extension (e.g. ".csv", ".xlsx"), not internal dots.
    text = re.sub(r"\.[a-z0-9]{1,5}$", "", text)
    # Non [a-z0-9_] runs -> single underscore.
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")

    if not text:
        return "dataset"
    if text[0].isdigit():
        text = f"col_{text}"
    if keyword.iskeyword(text) or keyword.issoftkeyword(text):
        text = f"{text}_"
    return text


def _to_jsonable(value: Any) -> Any:
    """Coerce a single cell value into a JSON-serializable scalar (NaN -> None)."""
    if value is None:
        return None
    # pandas NA / NaN / NaT
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (int, str, bool)):
        return value
    # numpy scalars, timestamps, and everything else -> stable string/py-native
    item = getattr(value, "item", None)
    if callable(item):
        try:
            converted = value.item()
            if isinstance(converted, float) and (
                math.isnan(converted) or math.isinf(converted)
            ):
                return None
            return converted
        except (ValueError, TypeError):
            pass
    return str(value)


def profile_dataframe(df: pd.DataFrame, sample_rows: int) -> dict:
    """Extract a schema + a bounded set of sample rows.

    Returns::

        {"n_rows": int, "n_cols": int,
         "columns": [{"name": str, "dtype": str}, ...],
         "sample_rows": [ {col: value, ...}, ... ]}   # <= sample_rows rows, JSON-safe
    """
    n = max(int(sample_rows), 0)
    columns = [
        {"name": str(name), "dtype": str(dtype)}
        for name, dtype in zip(df.columns, df.dtypes)
    ]
    head = df.head(n)
    sample: list[dict] = []
    col_names = [str(c) for c in df.columns]
    for _, row in head.iterrows():
        sample.append(
            {col_names[i]: _to_jsonable(row.iloc[i]) for i in range(len(col_names))}
        )
    return {
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": columns,
        "sample_rows": sample,
    }


def write_parquet(df: pd.DataFrame, path: str | Path) -> None:
    """Write the full DataFrame to parquet (normalized, for the sandbox)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, engine="pyarrow", index=False)
