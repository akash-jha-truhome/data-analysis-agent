from typing import TypedDict


class AgentState(TypedDict, total=False):
    """State for the code-execution loop (see spec/agent.md > Agent State)."""

    # Identity
    run_id: str                     # set by runner before invoke
    dataset_id: str                 # set by runner from the /ask request
    session_id: str | None          # Phase 2 — multi-turn session this run belongs to

    # Conversation memory (Phase 2)
    conversation: list              # prior turns [{role, content}] — text only, bounded

    # Input
    question: str                   # user's natural-language question
    schema: dict                    # {columns:[{name,dtype}], n_rows, n_cols} — set by prepare
    sample_rows: list               # <= sample_rows rows — set by prepare (LLM-visible)
    parquet_paths: dict             # {name: path} — set by prepare (sandbox-only, NOT LLM-visible)
    datasets: list                  # Phase 3 — per-dataset {var_name, schema, sample_rows} for the multi-source prompt

    # Pipeline data (populated progressively)
    plan: str | None                # brief plan text, part of write_code output
    code: str                       # latest generated pandas — set by write_code
    exec_result: dict               # ExecResult from execute
    step_trace: list                # [{step, action, code, ok, error, duration_ms}]
    attempt: int                    # retry counter — incremented on each write_code
    max_steps: int                  # bound (AGENT_MAX_STEPS) — set by runner/prepare

    # Output
    answer: str                     # final prose — set by answer
    key_numbers: list               # [{label, value}] — set by answer
    chart_hint: dict | None         # {type, x, y, series} — set by answer
    chart_spec: dict | None         # Plotly figure spec — set by build_chart
    result_table: dict | None       # {columns, rows} behind the answer — set from exec_result
    tokens: dict                    # {prompt, completion, total} — accumulated across LLM calls
    suggestions: list               # 2-3 follow-up question strings — set by answer (Phase 2)
    data_quality: dict | None       # deterministic quality flags — set by profile_quality (Phase 2)

    # Clarification gate (Phase 3 — folded into write_code, no extra LLM call)
    needs_clarification: bool        # set by write_code when the ask is genuinely ambiguous
    clarification_question: str | None  # the single question to ask the user
    clarification_answer: str | None    # the user's reply on a resume run (forces code)

    # Control
    error: str | None               # set by any node on fatal failure
    status: str                     # pending|completed|failed|needs_clarification
