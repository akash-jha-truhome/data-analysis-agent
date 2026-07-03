"""LangGraph nodes for the code-execution loop (see spec/agent.md > Nodes).

prepare -> write_code -> execute -> answer -> build_chart -> finalize
                 ^          |
                 └──────────┘  (bounded retry on code error)

Sibling-slice functions (``sandbox.executor.run_code``,
``observability.audit_log.append_audit``) are imported lazily inside the node
bodies so the graph module imports/compiles even before those slices land.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from graph.state import AgentState
from llm.client import LLMClient
from config.settings import get_settings
from observability.events import get_logger

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
_MAX_RESULT_ROWS_TO_LLM = 50  # cap rows of the COMPUTED table sent to the answer step

_log = get_logger("agent.graph")


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def _append_trace(state: AgentState, entry: dict) -> list:
    trace = list(state.get("step_trace") or [])
    entry = {"step": len(trace) + 1, **entry}
    trace.append(entry)
    return trace


def _accumulate_tokens(state: AgentState, usage: dict) -> dict:
    acc = dict(state.get("tokens") or {"prompt": 0, "completion": 0, "total": 0})
    acc["prompt"] = acc.get("prompt", 0) + int(usage.get("prompt", 0))
    acc["completion"] = acc.get("completion", 0) + int(usage.get("completion", 0))
    acc["total"] = acc.get("total", 0) + int(usage.get("total", 0))
    return acc


# --------------------------------------------------------------------------- #
# Prompt building + parsing (pure functions — unit-tested directly)
# --------------------------------------------------------------------------- #

def build_write_code_prompt(
    schema: dict,
    sample_rows: list,
    question: str,
    *,
    prior_code: str | None = None,
    traceback: str | None = None,
) -> str:
    """Assemble the write_code user prompt.

    CRITICAL CONTRACT (spec/architecture.md): the ONLY dataframe-derived content
    is the schema + at most ``AGENT_SAMPLE_ROWS`` sample rows. The full dataset
    is NEVER placed in this prompt.
    """
    columns = schema.get("columns", [])
    schema_lines = "\n".join(
        f"  - {c['name']} ({c['dtype']})" for c in columns
    )
    parts = [
        f"Dataset schema ({schema.get('n_rows', '?')} rows, {schema.get('n_cols', '?')} columns):",
        schema_lines,
        "",
        f"Sample rows (at most {len(sample_rows)} shown — NOT the full data):",
        json.dumps(sample_rows, ensure_ascii=False, default=str),
        "",
        f"Question: {question}",
    ]
    if prior_code and traceback:
        parts += [
            "",
            "Your previous code raised an error. Fix it.",
            "Previous code:",
            "```python",
            prior_code.strip(),
            "```",
            "Error / traceback:",
            traceback.strip(),
        ]
    return "\n".join(parts)


_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text: str) -> str:
    """Extract the python code from a fenced block; fall back to raw text."""
    m = _CODE_BLOCK_RE.search(text or "")
    if m:
        return m.group(1).strip()
    return (text or "").strip()


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> dict:
    """Parse a JSON object out of the answer text (tolerates a fenced block)."""
    if not text:
        raise ValueError("empty answer text")
    m = _JSON_BLOCK_RE.search(text)
    candidate = m.group(1).strip() if m else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: grab the outermost {...}
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(candidate[start : end + 1])
        raise


def _result_table_for_answer(result_table: dict | None, result_repr: str | None) -> str:
    if result_table and result_table.get("columns"):
        capped = {
            "columns": result_table["columns"],
            "rows": result_table.get("rows", [])[:_MAX_RESULT_ROWS_TO_LLM],
        }
        return json.dumps(capped, ensure_ascii=False, default=str)
    return f"Scalar result: {result_repr}"


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #

def prepare(state: AgentState) -> AgentState:
    """Load schema + sample rows + parquet path from the dataset store."""
    from datasets.store import get_dataset_meta

    settings = get_settings()
    dataset_id = state.get("dataset_id", "")
    try:
        meta = get_dataset_meta(dataset_id)
    except Exception as exc:  # store/DB failure is fatal
        return {**state, "error": f"Failed to load dataset: {exc}"}

    if meta is None:
        return {**state, "error": f"Dataset not found: {dataset_id}"}

    schema = {
        "columns": meta["columns"],
        "n_rows": meta["n_rows"],
        "n_cols": meta["n_cols"],
    }
    return {
        **state,
        "schema": schema,
        "sample_rows": meta["sample_rows"],
        "parquet_paths": {"df": meta["parquet_path"]},
        "attempt": 0,
        "max_steps": state.get("max_steps", settings.max_steps),
        "step_trace": list(state.get("step_trace") or []),
        "tokens": state.get("tokens") or {"prompt": 0, "completion": 0, "total": 0},
    }


def write_code(state: AgentState) -> AgentState:
    """Gemini Flash: schema + sample rows + question -> pandas assigning `result`."""
    started = time.monotonic()
    system = _load_prompt("write_code.md")

    prior_code = None
    traceback = None
    exec_result = state.get("exec_result")
    if exec_result and not exec_result.get("ok"):
        prior_code = state.get("code")
        traceback = exec_result.get("traceback") or exec_result.get("error")

    prompt = build_write_code_prompt(
        state.get("schema", {}),
        state.get("sample_rows", []),
        state.get("question", ""),
        prior_code=prior_code,
        traceback=traceback,
    )

    try:
        text, usage = LLMClient().call_with_usage(prompt, system=system)
    except Exception as exc:
        return {**state, "error": f"LLM (write_code) failed: {exc}"}

    code = extract_code(text)
    attempt = int(state.get("attempt", 0)) + 1
    duration_ms = int((time.monotonic() - started) * 1000)
    trace = _append_trace(
        state,
        {"action": "write_code", "code": code, "ok": True, "error": None, "duration_ms": duration_ms},
    )
    return {
        **state,
        "code": code,
        "plan": text,
        "attempt": attempt,
        "tokens": _accumulate_tokens(state, usage),
        "step_trace": trace,
    }


def execute(state: AgentState) -> AgentState:
    """Run the generated pandas in the sandbox subprocess against the full data."""
    from sandbox.executor import run_code

    settings = get_settings()
    started = time.monotonic()
    code = state.get("code", "")
    try:
        exec_result = run_code(
            code,
            state.get("parquet_paths", {}),
            timeout_s=settings.sandbox_timeout_s,
            mem_mb=settings.sandbox_mem_mb,
        )
    except Exception as exc:
        # Sandbox INFRASTRUCTURE failure (not a code error) — fatal.
        duration_ms = int((time.monotonic() - started) * 1000)
        trace = _append_trace(
            state,
            {"action": "execute", "code": code, "ok": False, "error": str(exc), "duration_ms": duration_ms},
        )
        return {**state, "error": f"Sandbox infrastructure failure: {exc}", "step_trace": trace}

    ok = bool(exec_result.get("ok"))
    trace = _append_trace(
        state,
        {
            "action": "execute",
            "code": code,
            "ok": ok,
            "error": None if ok else (exec_result.get("error") or "code error"),
            "duration_ms": exec_result.get("duration_ms", int((time.monotonic() - started) * 1000)),
        },
    )
    # Note: a code error does NOT set state["error"] — the retry loop handles it.
    return {
        **state,
        "exec_result": exec_result,
        "result_table": exec_result.get("result_table"),
        "step_trace": trace,
    }


def answer(state: AgentState) -> AgentState:
    """Gemini Flash: question + COMPUTED result table -> strict JSON answer."""
    started = time.monotonic()
    system = _load_prompt("answer.md")
    exec_result = state.get("exec_result") or {}
    result_str = _result_table_for_answer(
        state.get("result_table"), exec_result.get("result_repr")
    )
    base_prompt = (
        f"Question: {state.get('question', '')}\n\n"
        f"Computed result table (ground truth):\n{result_str}"
    )

    usage_total = {"prompt": 0, "completion": 0, "total": 0}
    parsed = None
    last_error = None
    for attempt in range(2):  # initial + one reformat retry on JSON failure
        prompt = base_prompt
        if attempt == 1:
            prompt += "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
        try:
            text, usage = LLMClient().call_with_usage(prompt, system=system)
        except Exception as exc:
            return {
                **state,
                "error": f"LLM (answer) failed: {exc}",
                "tokens": _accumulate_tokens(state, usage_total),
            }
        for k in usage_total:
            usage_total[k] += int(usage.get(k, 0))
        try:
            parsed = extract_json(text)
            break
        except Exception as exc:  # noqa: BLE001 - JSON parse failure -> retry once
            last_error = exc

    tokens = _accumulate_tokens(state, usage_total)
    if parsed is None:
        return {**state, "error": f"answer JSON parse failed: {last_error}", "tokens": tokens}

    key_numbers = parsed.get("key_numbers") or []
    if not isinstance(key_numbers, list):
        key_numbers = []
    duration_ms = int((time.monotonic() - started) * 1000)
    trace = _append_trace(
        state,
        {"action": "answer", "code": None, "ok": True, "error": None, "duration_ms": duration_ms},
    )
    return {
        **state,
        "answer": parsed.get("answer", ""),
        "key_numbers": key_numbers,
        "chart_hint": parsed.get("chart") or {},
        "tokens": tokens,
        "step_trace": trace,
    }


def build_chart(state: AgentState) -> AgentState:
    """Deterministic Plotly spec from the chart hint + result table (never fails)."""
    from charts.spec import build_chart_spec

    try:
        spec = build_chart_spec(state.get("chart_hint"), state.get("result_table"))
    except Exception as exc:  # never fail the run on a chart problem
        _log.warning("build_chart_failed", error=str(exc), run_id=state.get("run_id"))
        spec = {"data": [], "layout": {"title": "Result"}, "table_only": True}
    return {**state, "chart_spec": spec}


def _persist_run(state: AgentState, status: str) -> None:
    from db.session import create_db_session
    from db.models import RunRow

    run_id = state.get("run_id")
    if not run_id:
        return
    with create_db_session() as session:
        run = session.get(RunRow, run_id)
        if run is None:
            return
        run.status = status
        run.dataset_id = state.get("dataset_id")
        run.question = state.get("question")
        run.generated_code = state.get("code")
        run.answer_text = state.get("answer")
        rt = state.get("result_table")
        run.result_json = json.dumps(rt) if rt is not None else None
        kn = state.get("key_numbers")
        run.key_numbers_json = json.dumps(kn) if kn is not None else None
        cs = state.get("chart_spec")
        run.chart_json = json.dumps(cs) if cs is not None else None
        st = state.get("step_trace")
        run.step_trace_json = json.dumps(st) if st is not None else None
        tokens = state.get("tokens") or {}
        run.prompt_tokens = tokens.get("prompt")
        run.completion_tokens = tokens.get("completion")
        run.total_tokens = tokens.get("total")
        run.error_message = state.get("error")


def _append_audit_safe(record: dict) -> None:
    try:
        from observability.audit_log import append_audit
    except Exception:  # audit_log slice not yet available — don't break the run
        return
    try:
        append_audit(record)
    except Exception as exc:  # audit must never fail the run
        _log.warning("audit_append_failed", error=str(exc), run_id=record.get("run_id"))


def _audit_record(state: AgentState, status: str) -> dict:
    return {
        "run_id": state.get("run_id"),
        "dataset_id": state.get("dataset_id"),
        "question": state.get("question"),
        "code": state.get("code"),
        "result": state.get("result_table"),
        "tokens": state.get("tokens"),
        "status": status,
        "error": state.get("error"),
    }


def finalize(state: AgentState) -> AgentState:
    """Persist the completed run to SQLite + audit log; emit a structlog line."""
    _persist_run(state, "completed")
    _append_audit_safe(_audit_record(state, "completed"))
    tokens = state.get("tokens") or {}
    _log.info(
        "run_completed",
        run_id=state.get("run_id"),
        dataset_id=state.get("dataset_id"),
        question=state.get("question"),
        total_tokens=tokens.get("total"),
        steps=len(state.get("step_trace") or []),
        status="completed",
    )
    return {**state, "status": "completed"}


def handle_error(state: AgentState) -> AgentState:
    """Persist the failed run + trace; emit a structlog line. Never fabricates output."""
    _persist_run(state, "failed")
    _append_audit_safe(_audit_record(state, "failed"))
    _log.warning(
        "run_failed",
        run_id=state.get("run_id"),
        dataset_id=state.get("dataset_id"),
        error=state.get("error"),
        steps=len(state.get("step_trace") or []),
        status="failed",
    )
    return {**state, "status": "failed"}
