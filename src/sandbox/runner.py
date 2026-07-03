"""Child-process entry point for the pandas sandbox.

Runs as a short-lived, resource-bounded, network-free subprocess:

    python -m sandbox.runner   # request JSON on stdin, envelope JSON on stdout

It reads a JSON request from stdin, applies POSIX resource limits (memory +
CPU) where available, loads each parquet file into a dataframe bound to its
variable name, executes the supplied pandas code in a restricted namespace
exposing only ``pd``, ``np`` and the dataframe(s), then normalizes the
``result`` variable into a JSON-serializable envelope printed to stdout.

The process never imports network libraries and performs no network calls;
being a bounded, isolated child process is the sandbox boundary (full OS-level
firewalling is out of scope for this local personal tool — documented in
spec/architecture.md as an accepted assumption).
"""
from __future__ import annotations

import builtins
import contextlib
import datetime
import io
import json
import math
import sys
import traceback

import numpy as np
import pandas as pd

DEFAULT_MAX_RESULT_ROWS = 1000
_REPR_CAP = 500

# Curated builtins: everything an analysis snippet plausibly needs, minus the
# escape hatches (``open``, ``__import__``, ``eval``, ``exec``, ``compile``,
# ``input``) so the executed code cannot open files, import network libraries,
# or spawn further evaluation.
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "getattr",
    "hasattr", "hash", "hex", "int", "isinstance", "issubclass", "iter",
    "len", "list", "map", "max", "min", "next", "oct", "ord", "pow",
    "print", "range", "repr", "reversed", "round", "set", "setattr",
    "slice", "sorted", "str", "sum", "tuple", "type", "zip",
)


def _safe_builtins() -> dict:
    ns = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES if hasattr(builtins, name)}
    ns["True"] = True
    ns["False"] = False
    ns["None"] = None
    return ns


def _apply_resource_limits(mem_mb: int, cpu_s: int) -> None:
    """Best-effort memory + CPU caps. Degrades gracefully off POSIX."""
    try:
        import resource
    except ImportError:  # non-POSIX (e.g. Windows) — parent wall-clock is the guard
        return

    for limit_name, value in (
        ("RLIMIT_AS", mem_mb * 1024 * 1024),
        ("RLIMIT_CPU", cpu_s),
    ):
        rlimit = getattr(resource, limit_name, None)
        if rlimit is None:
            continue
        try:
            soft, hard = resource.getrlimit(rlimit)
            new_hard = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(rlimit, (min(value, new_hard), new_hard))
        except (ValueError, OSError):
            # Some platforms (notably macOS) reject RLIMIT_AS; the wall-clock
            # timeout in the parent remains the hard guard. Never crash here.
            continue


def _clean(value):
    """Convert a single cell into a JSON-serializable python value."""
    if value is None:
        return None
    try:
        if np.ndim(value) == 0 and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.timedelta64):
        return str(pd.Timedelta(value))
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (np.ndarray, list, tuple)):
        return [_clean(v) for v in list(value)]
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (int, str)):
        return value
    return str(value)


def _dataframe_table(df: pd.DataFrame, max_rows: int) -> dict:
    columns = [str(c) for c in df.columns]
    capped = df.head(max_rows)
    rows = [[_clean(v) for v in record] for record in capped.itertuples(index=False, name=None)]
    return {"columns": columns, "rows": rows}


def _series_table(series: pd.Series, max_rows: int) -> dict:
    index_name = str(series.index.name) if series.index.name is not None else "index"
    value_name = str(series.name) if series.name is not None else "value"
    capped = series.head(max_rows)
    rows = [[_clean(idx), _clean(val)] for idx, val in capped.items()]
    return {"columns": [index_name, value_name], "rows": rows}


def _normalize_result(result, max_rows: int) -> dict:
    if isinstance(result, pd.DataFrame):
        return _dataframe_table(result, max_rows)
    if isinstance(result, pd.Series):
        return _series_table(result, max_rows)
    if isinstance(result, pd.Index):
        return _series_table(pd.Series(result), max_rows)
    # Array-likes (numpy arrays, pandas ExtensionArrays like ArrowStringArray from
    # .unique(), plain lists/tuples) -> one value per row, not a single ugly cell.
    if isinstance(result, (np.ndarray, list, tuple)) or isinstance(
        result, pd.api.extensions.ExtensionArray
    ):
        values = list(result)
        return {"columns": ["value"], "rows": [[_clean(v)] for v in values[:max_rows]]}
    return {"columns": ["value"], "rows": [[_clean(result)]]}


def _run(request: dict) -> dict:
    code = request["code"]
    parquet_paths = request["parquet_paths"]
    max_rows = int(request.get("max_result_rows", DEFAULT_MAX_RESULT_ROWS))

    namespace: dict = {"pd": pd, "np": np, "__builtins__": _safe_builtins()}
    for var_name, path in parquet_paths.items():
        namespace[var_name] = pd.read_parquet(path)

    user_stdout = io.StringIO()
    try:
        compiled = compile(code, "<generated>", "exec")
        with contextlib.redirect_stdout(user_stdout):
            exec(compiled, namespace)  # noqa: S102 — sandboxed child, restricted builtins
    except Exception:
        tb = traceback.format_exc()
        return {
            "ok": False,
            "result_table": None,
            "result_repr": None,
            "stdout": user_stdout.getvalue(),
            "error": tb.strip().splitlines()[-1] if tb.strip() else "execution error",
            "traceback": tb,
        }

    if "result" not in namespace:
        return {
            "ok": False,
            "result_table": None,
            "result_repr": None,
            "stdout": user_stdout.getvalue(),
            "error": "code did not assign a `result` variable",
            "traceback": None,
        }

    result = namespace["result"]
    try:
        table = _normalize_result(result, max_rows)
    except Exception:
        tb = traceback.format_exc()
        return {
            "ok": False,
            "result_table": None,
            "result_repr": None,
            "stdout": user_stdout.getvalue(),
            "error": "failed to serialize result: " + tb.strip().splitlines()[-1],
            "traceback": tb,
        }

    return {
        "ok": True,
        "result_table": table,
        "result_repr": str(result)[:_REPR_CAP],
        "stdout": user_stdout.getvalue(),
        "error": None,
        "traceback": None,
    }


def main() -> None:
    raw = sys.stdin.read()
    request = json.loads(raw)
    _apply_resource_limits(
        mem_mb=int(request.get("mem_mb", 2048)),
        cpu_s=int(request.get("cpu_s", 30)),
    )
    envelope = _run(request)
    sys.stdout.write(json.dumps(envelope))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
