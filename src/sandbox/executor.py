"""Parent-side driver for the bounded pandas sandbox.

``run_code`` spawns a fresh, short-lived child process (``sandbox.runner``),
feeds it the generated pandas code plus the parquet paths to load, and enforces
a wall-clock timeout. It returns a fully JSON-serializable ``ExecResult`` dict.
It never raises for a *code* error (bad pandas, missing ``result``, timeout) —
those come back as ``ok=False`` so the agent graph can retry. Only genuine
infrastructure failures (cannot spawn the interpreter) propagate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent
_CPU_MARGIN_S = 5  # RLIMIT_CPU is a backstop; the wall-clock timeout wins first.
_MAX_RESULT_ROWS = 1000

# Minimal environment: enough for the interpreter + pandas/pyarrow to run, but
# nothing application-specific. The child is import-restricted and does no
# network I/O by construction.
_ENV_ALLOWLIST = (
    "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
    "SYSTEMROOT", "PYTHONHASHSEED", "PYTHONUTF8",
)


def _child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    env["PYTHONPATH"] = str(_SRC_DIR)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_code(
    code: str,
    parquet_paths: dict[str, str],
    *,
    timeout_s: int,
    mem_mb: int,
) -> dict:
    """Run generated pandas in a bounded, network-free child process.

    ``parquet_paths`` maps a dataframe variable name -> parquet file path. For
    Phase 1 there is one entry, key ``"df"`` (the loaded dataset). The generated
    ``code`` reads the dataframes by those variable names and MUST assign its
    output to a variable named ``result`` (a pandas DataFrame, Series, or
    scalar).

    Returns an ExecResult dict with EXACTLY these keys:
      { "ok": bool,
        "result_table": {"columns": list[str], "rows": list[list]} | None,
        "result_repr": str,
        "stdout": str,
        "error": str | None,
        "traceback": str | None,
        "duration_ms": int }
    """
    request = json.dumps(
        {
            "code": code,
            "parquet_paths": parquet_paths,
            "mem_mb": mem_mb,
            "cpu_s": timeout_s + _CPU_MARGIN_S,
            "max_result_rows": _MAX_RESULT_ROWS,
        }
    )

    start = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "sandbox.runner"],
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(_SRC_DIR),
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return _result(
            ok=False,
            error="execution timed out",
            traceback=None,
            duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    envelope = _parse_envelope(completed.stdout)
    if envelope is None:
        # No parseable envelope on stdout: the child died before reporting
        # (e.g. OOM kill via RLIMIT_AS / SIGXCPU). Surface stderr as the trace.
        stderr = (completed.stderr or "").strip()
        error = _summarize_child_failure(completed.returncode, stderr)
        return _result(
            ok=False,
            error=error,
            traceback=stderr or None,
            duration_ms=duration_ms,
        )

    envelope["duration_ms"] = duration_ms
    return envelope


def _parse_envelope(stdout: str) -> dict | None:
    stdout = (stdout or "").strip()
    if not stdout:
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "ok" not in data:
        return None
    return data


def _summarize_child_failure(returncode: int, stderr: str) -> str:
    if returncode and returncode < 0:
        return f"sandbox process killed by signal {-returncode} (possible memory/CPU limit)"
    last_line = stderr.splitlines()[-1] if stderr else ""
    return last_line or f"sandbox process exited with code {returncode}"


def _result(*, ok: bool, error: str | None, traceback: str | None, duration_ms: int) -> dict:
    return {
        "ok": ok,
        "result_table": None,
        "result_repr": None,
        "stdout": "",
        "error": error,
        "traceback": traceback,
        "duration_ms": duration_ms,
    }
