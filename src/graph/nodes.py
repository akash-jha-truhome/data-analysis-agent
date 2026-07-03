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

_MAX_CONVERSATION_TURNS = 6  # bound prior turns injected into write_code
_MAX_TURN_CHARS = 500        # bound the length of each prior turn's text


def _conversation_block(conversation: list | None) -> list[str]:
    """Render prior turns as TEXT ONLY (question + brief answer summary).

    CRITICAL: this carries prior-turn *text* so follow-ups resolve against
    context; it NEVER carries dataframe rows. Bounded to the last few turns.
    """
    turns = [t for t in (conversation or []) if t.get("content")]
    if not turns:
        return []
    turns = turns[-_MAX_CONVERSATION_TURNS:]
    lines = ["Conversation so far (prior turns — resolve follow-ups against this):"]
    for turn in turns:
        role = str(turn.get("role", "user"))
        content = str(turn.get("content", ""))[:_MAX_TURN_CHARS]
        lines.append(f"  {role}: {content}")
    lines.append("")
    return lines


def _render_one_dataset(var_name: str, schema: dict, sample_rows: list, *, header: str) -> list[str]:
    columns = schema.get("columns", [])
    schema_lines = "\n".join(f"  - {c['name']} ({c['dtype']})" for c in columns)
    return [
        f"{header} ({schema.get('n_rows', '?')} rows, {schema.get('n_cols', '?')} columns):",
        schema_lines,
        "",
        f"Sample rows (at most {len(sample_rows)} shown — NOT the full data):",
        json.dumps(sample_rows, ensure_ascii=False, default=str),
        "",
    ]


def build_write_code_prompt(
    schema: dict,
    sample_rows: list,
    question: str,
    *,
    conversation: list | None = None,
    prior_code: str | None = None,
    traceback: str | None = None,
    datasets: list | None = None,
    clarification_answer: str | None = None,
) -> str:
    """Assemble the write_code user prompt.

    CRITICAL CONTRACT (spec/architecture.md): the ONLY dataframe-derived content
    is the schema + at most ``AGENT_SAMPLE_ROWS`` sample rows PER dataset. The
    full dataset is NEVER placed in this prompt. Prior conversation turns are
    TEXT ONLY.

    Phase 3: when ``datasets`` carries more than one loaded source, each is
    rendered with ITS OWN variable name + schema + ≤ sample rows so the LLM can
    write ``orders.merge(customers, ...)``. A single dataset (var ``df``) renders
    exactly as before for backward compatibility.
    """
    parts = list(_conversation_block(conversation))

    multi = datasets is not None and len(datasets) > 1
    if multi:
        parts.append(
            "Multiple datasets are loaded, each already available as a named "
            "pandas DataFrame variable. Write code that references them BY NAME "
            "(e.g. join/compare across them) and assigns the answer to `result`."
        )
        parts.append("")
        for d in datasets:
            parts += _render_one_dataset(
                d["var_name"],
                d.get("schema", {}),
                d.get("sample_rows", []),
                header=f"Dataset `{d['var_name']}`",
            )
        parts.append(f"Question: {question}")
    else:
        parts += _render_one_dataset(
            "df", schema, sample_rows, header="Dataset schema"
        )
        parts.append(f"Question: {question}")

    if clarification_answer:
        parts += [
            "",
            f"The user clarified: {clarification_answer}. "
            "Now write the pandas code — do NOT ask another question.",
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


def extract_clarify(text: str) -> str | None:
    """Detect a ``{"clarify": "<question>"}`` response (instead of code).

    Conservative: if the model returned a python code block we treat it as code,
    never a clarification. Only a JSON object carrying a non-empty ``clarify``
    string counts as a clarification request.
    """
    if not text or _CODE_BLOCK_RE.search(text):
        return None
    try:
        obj = extract_json(text)
    except Exception:  # noqa: BLE001 — not JSON -> it's code/prose, not a clarify
        return None
    if isinstance(obj, dict):
        q = obj.get("clarify")
        if isinstance(q, str) and q.strip():
            return q.strip()
    return None


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

def _session_datasets(session_id: str | None) -> list | None:
    """All datasets linked to the session (Phase 3), or None if unavailable.

    Imported lazily + guarded so the graph still works before the multi-data
    slice lands and for the single-file path (no session / one dataset).
    """
    if not session_id:
        return None
    try:
        from datasets.store import get_session_datasets
    except Exception:  # multi-data slice not present yet
        return None
    try:
        return get_session_datasets(session_id)
    except Exception:
        return None


def prepare(state: AgentState) -> AgentState:
    """Load schema + sample rows + parquet path(s) from the dataset store.

    Phase 3: if the session has MULTIPLE linked datasets, load them all — each
    bound to its own variable name — and build the per-dataset prompt payload.
    Otherwise fall back to the exact single-dataset path (var ``df``).
    """
    from datasets.store import get_dataset_meta

    settings = get_settings()
    dataset_id = state.get("dataset_id", "")
    base = {
        "attempt": 0,
        "max_steps": state.get("max_steps", settings.max_steps),
        "step_trace": list(state.get("step_trace") or []),
        "tokens": state.get("tokens") or {"prompt": 0, "completion": 0, "total": 0},
    }

    linked = _session_datasets(state.get("session_id"))
    if linked and len(linked) > 1:
        parquet_paths: dict = {}
        datasets: list = []
        for d in linked:
            var = d["var_name"]
            schema = {
                "columns": d["columns"],
                "n_rows": d["n_rows"],
                "n_cols": d["n_cols"],
            }
            parquet_paths[var] = d["parquet_path"]
            datasets.append(
                {"var_name": var, "schema": schema, "sample_rows": d["sample_rows"]}
            )
        primary = datasets[0]
        return {
            **state,
            **base,
            "schema": primary["schema"],
            "sample_rows": primary["sample_rows"],
            "parquet_paths": parquet_paths,
            "datasets": datasets,
        }

    # Single-dataset path — preserved exactly.
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
        **base,
        "schema": schema,
        "sample_rows": meta["sample_rows"],
        "parquet_paths": {"df": meta["parquet_path"]},
        "datasets": [
            {"var_name": "df", "schema": schema, "sample_rows": meta["sample_rows"]}
        ],
    }


# --------------------------------------------------------------------------- #
# Data-quality profiling (DETERMINISTIC — no LLM; runs in the real sandbox)
# --------------------------------------------------------------------------- #

# Canned pandas profiling script. Computed over the FULL parquet in the same
# bounded, network-free sandbox the agent uses for generated code. Assigns a
# plain dict to `result`; the sandbox serializes it into a one-cell table which
# `profile_quality` unpacks. Uses only the sandbox's restricted builtins.
_QUALITY_SCRIPT = """
n_rows = len(df)
missing = []
for col in df.columns:
    cnt = int(df[col].isna().sum())
    if cnt > 0:
        pct = round(100.0 * cnt / n_rows, 2) if n_rows else 0.0
        missing.append({"column": str(col), "count": cnt, "pct": pct})

duplicate_rows = int(df.duplicated().sum())

outliers = []
numeric = df.select_dtypes(include="number")
for col in numeric.columns:
    s = numeric[col].dropna()
    if len(s) < 4:
        continue
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        continue
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    cnt = int(((s < lo) | (s > hi)).sum())
    if cnt > 0:
        outliers.append({"column": str(col), "count": cnt})

parts = []
if missing:
    parts.append(str(len(missing)) + " column(s) with missing values")
if duplicate_rows:
    parts.append(str(duplicate_rows) + " duplicate row(s)")
if outliers:
    parts.append("outliers in " + str(len(outliers)) + " numeric column(s)")
summary = "; ".join(parts) if parts else "No data-quality issues detected."

result = {
    "missing": missing,
    "duplicate_rows": duplicate_rows,
    "outliers": outliers,
    "summary": summary,
}
"""

# In-process cache: quality is a property of the dataset, not the question, so
# repeated questions in a session don't recompute the profile.
_QUALITY_CACHE: dict[str, dict] = {}


def _empty_quality() -> dict:
    return {"missing": [], "duplicate_rows": 0, "outliers": [], "summary": ""}


def profile_quality(state: AgentState) -> AgentState:
    """Deterministically flag data-quality issues (missing/duplicates/outliers).

    Runs the canned profiling script in the real sandbox over the full parquet.
    MUST NEVER fail the run — degrades to ``{}`` on any error. Cached per
    dataset_id so repeated questions in a session don't recompute.
    """
    dataset_id = state.get("dataset_id", "")
    if dataset_id in _QUALITY_CACHE:
        return {**state, "data_quality": _QUALITY_CACHE[dataset_id]}

    dq: dict = {}
    try:
        from sandbox.executor import run_code

        settings = get_settings()
        exec_result = run_code(
            _QUALITY_SCRIPT,
            state.get("parquet_paths", {}),
            timeout_s=settings.sandbox_timeout_s,
            mem_mb=settings.sandbox_mem_mb,
        )
        if exec_result.get("ok"):
            table = exec_result.get("result_table") or {}
            rows = table.get("rows") or []
            if rows and rows[0] and isinstance(rows[0][0], dict):
                dq = rows[0][0]
    except Exception as exc:  # profiling must NEVER fail the run
        _log.warning("profile_quality_failed", error=str(exc), run_id=state.get("run_id"))
        dq = {}

    if dataset_id:
        _QUALITY_CACHE[dataset_id] = dq
    return {**state, "data_quality": dq}


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

    clarification_answer = state.get("clarification_answer")
    prompt = build_write_code_prompt(
        state.get("schema", {}),
        state.get("sample_rows", []),
        state.get("question", ""),
        conversation=state.get("conversation"),
        prior_code=prior_code,
        traceback=traceback,
        datasets=state.get("datasets"),
        clarification_answer=clarification_answer,
    )

    try:
        text, usage = LLMClient().call_with_usage(prompt, system=system)
    except Exception as exc:
        return {**state, "error": f"LLM (write_code) failed: {exc}"}

    tokens = _accumulate_tokens(state, usage)
    attempt = int(state.get("attempt", 0)) + 1

    # Clarification gate — folded into THIS call (no extra LLM round-trip). If the
    # user has already answered a clarification, ignore any further clarify and
    # force code. Only clarify on a genuine, first-time ambiguity.
    clarify_q = None if clarification_answer else extract_clarify(text)
    if clarify_q:
        duration_ms = int((time.monotonic() - started) * 1000)
        trace = _append_trace(
            state,
            {
                "action": "clarify_request",
                "code": None,
                "clarification_question": clarify_q,
                "ok": True,
                "error": None,
                "duration_ms": duration_ms,
            },
        )
        return {
            **state,
            "needs_clarification": True,
            "clarification_question": clarify_q,
            "plan": text,
            "attempt": attempt,
            "tokens": tokens,
            "step_trace": trace,
        }

    code = extract_code(text)
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
        "needs_clarification": False,
        "tokens": tokens,
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
    # Follow-up suggestions are BATCHED into this same answer call (no extra LLM
    # call) — keep 2-3 concise strings.
    suggestions = parsed.get("suggestions") or []
    if not isinstance(suggestions, list):
        suggestions = []
    suggestions = [str(s) for s in suggestions if s][:3]
    duration_ms = int((time.monotonic() - started) * 1000)
    trace = _append_trace(
        state,
        {"action": "answer", "code": None, "ok": True, "error": None, "duration_ms": duration_ms},
    )
    return {
        **state,
        "answer": parsed.get("answer", ""),
        "key_numbers": key_numbers,
        "suggestions": suggestions,
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
        sg = state.get("suggestions")
        run.suggestions_json = json.dumps(sg) if sg is not None else None
        dq = state.get("data_quality")
        run.data_quality_json = json.dumps(dq) if dq is not None else None
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


def clarify(state: AgentState) -> AgentState:
    """Terminal Phase-3 node: the ask was genuinely ambiguous.

    Persists the run with status ``needs_clarification`` (the question is carried
    in the ``clarify_request`` step-trace entry — no new DB column, no fabricated
    answer/number) and emits a structlog line. The user replies and the run is
    re-issued with ``clarification_answer`` set, which forces code next time.
    """
    _persist_run(state, "needs_clarification")
    _append_audit_safe(_audit_record(state, "needs_clarification"))
    _log.info(
        "run_needs_clarification",
        run_id=state.get("run_id"),
        dataset_id=state.get("dataset_id"),
        question=state.get("question"),
        clarification=state.get("clarification_question"),
        status="needs_clarification",
    )
    return {**state, "status": "needs_clarification"}


def handle_error(state: AgentState) -> AgentState:
    """Persist the failed run + trace; emit a structlog line. Never fabricates output."""
    if not state.get("error"):
        # Retries were exhausted on repeated code errors — execute() leaves
        # state["error"] unset so the loop can retry, so record WHY it gave up
        # from the last execution attempt (never leave the failure unexplained).
        exec_result = state.get("exec_result") or {}
        last_error = exec_result.get("error") or exec_result.get("traceback")
        attempts = int(state.get("attempt", 0))
        state = {
            **state,
            "error": (
                f"Could not produce a runnable answer after {attempts} attempt(s): {last_error}"
                if last_error
                else f"Could not produce a runnable answer after {attempts} attempt(s)."
            ),
        }
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
