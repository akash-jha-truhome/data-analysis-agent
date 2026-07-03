# Agent

The LangGraph agent that turns a natural-language question into an executed-pandas answer. Patterns are chosen from `harness/patterns/agentic-ai.md`.

---

## Agent Architecture Pattern

**Chosen:** **ReAct code-execution loop** — LLM-Generated Code Execution (#22) wrapped in a bounded Reflection/Exception-Recovery loop (#4 + #12), with light Planning (#6) folded into the code-writing step. The agent reasons → writes pandas → acts (runs it in the sandbox) → observes the real result or traceback → repeats on error up to `max_steps`, then answers. This is the correct floor for "arbitrary questions over structured data": never a hardcoded op-list (explicit anti-pattern in #22), always real generated code executed on the real data. Multi-agent/heavy-planning are deliberately NOT used — a single loop with two Flash calls per query meets the requirement at minimal cost.

| Pattern | Use when |
|---------|----------|
| **Single-agent loop** | One LLM drives a deterministic tool-call loop. No branches, no handoffs. |
| **Graph (LangGraph)** | Multi-step pipeline with conditional edges, checkpointing, or parallel nodes. ← **chosen** (bounded retry cycle) |
| **Multi-agent** | Specialised sub-agents; orchestrator routes. |
| **Supervisor** | One supervisor dispatches to workers. |
| **Human-in-the-loop** | Execution pauses for user review. (Phase 3 clarification gate only.) |

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `write_code` | Google Gemini | `gemini-3.5-flash` | Cheap, fast code generation from schema + samples; minimize cost. |
| `answer` | Google Gemini | `gemini-3.5-flash` | Cheap, fast prose + structured chart hint from the computed result. |

No LLM in `prepare`, `execute`, `build_chart`, `finalize`, `handle_error` (deterministic). **2 LLM calls per successful query; +1 per retry.**

**Fallback behaviour:** transient Gemini errors (5xx/rate-limit) → retry with exponential backoff (max 3, `google-genai` + wrapper). Hard failure or exhausted retries → route to `handle_error`, mark run `failed`, return a clean `api_error`. **Never fabricate a number** if code could not run — surface the failure. (Test path calls the real API; this is production resilience, not an offline stub.)

**Prompt strategy:** system/user split, structured output. `write_code` returns a fenced ```python block assigning `result` (parsed out). `answer` returns strict JSON `{answer, key_numbers:[{label,value}], chart:{type,x,y,series}}` (validated; on parse failure, one reformat retry then `handle_error`). Prompts carry **only** schema + `sample_rows` (never full data); the retry prompt appends the prior code + traceback.

---

## Tools & Tool Calling

The agent's single "tool" is the sandboxed pandas executor, invoked deterministically by the `execute` node (not via LLM function-calling — the loop is graph-driven for auditability).

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `sandbox.run_code` | Run generated pandas in a bounded, network-free subprocess against the full dataframe(s) loaded from parquet | `code: str`, `parquet_paths: dict`, `timeout_s`, `mem_mb` | `ExecResult {ok, result_table, result_repr, stdout, error, traceback, duration_ms}` | Spawns a child process; no DB/network writes |

**Tool selection strategy:** forced/single — `execute` always calls `sandbox.run_code` with the latest generated code. No LLM tool-choice.

**Tool failure handling:** on `ok=False`, `route_after_execute` retries `write_code` with the traceback while `attempt < max_steps`; on exhaustion, `handle_error`.

---

## Agent State

```python
class AgentState(TypedDict, total=False):
    # Identity
    run_id: str                     # set by runner before invoke
    dataset_id: str                 # set by runner from the /ask request

    # Input
    question: str                   # user's natural-language question
    schema: dict                    # {columns:[{name,dtype}], n_rows, n_cols} — set by prepare
    sample_rows: list               # ≤ sample_rows rows — set by prepare (LLM-visible)
    parquet_paths: dict             # {name: path} — set by prepare (sandbox-only, NOT LLM-visible)

    # Pipeline data (populated progressively)
    plan: str | None                # brief plan text, part of write_code output
    code: str                       # latest generated pandas — set by write_code
    exec_result: dict               # ExecResult from execute
    step_trace: list                # [{step, action, code, ok, error, duration_ms}] — appended each step
    attempt: int                    # retry counter — incremented on each write_code
    max_steps: int                  # bound (AGENT_MAX_STEPS, default 3) — set by runner

    # Output
    answer: str                     # final prose — set by answer
    key_numbers: list               # [{label, value}] — set by answer
    chart_spec: dict | None         # Plotly figure spec — set by build_chart
    result_table: dict | None       # {columns, rows} behind the answer — set from exec_result
    tokens: dict                    # {prompt, completion, total} — accumulated across LLM calls

    # Control
    error: str | None               # set by any node on fatal failure
    status: str                     # pending|completed|failed — set by finalize/handle_error
```

---

## Nodes / Steps

### `prepare`
**Reads:** `dataset_id`. **Writes:** `schema`, `sample_rows`, `parquet_paths`, `step_trace`, `attempt=0`.
**LLM:** no. **Behaviour:** loads dataset metadata from the dataset store (schema + sample rows + parquet path). Full data is NOT loaded into the process here. On missing dataset → set `error`.

### `write_code`
**Reads:** `question`, `schema`, `sample_rows`, `code`+`exec_result` (on retry). **Writes:** `code`, `plan`, `attempt+=1`, `tokens`, `step_trace`.
**LLM:** yes — `gemini-3.5-flash`, prompt `src/prompts/write_code.md`; input is schema + `sample_rows` + question (+ prior code + traceback on retry); output is a brief plan + a ```python block assigning `result`.
**External calls:** Gemini (transient → retry/backoff; hard → set `error`).

### `execute`
**Reads:** `code`, `parquet_paths`. **Writes:** `exec_result`, `result_table`, `step_trace`.
**LLM:** no. **Behaviour:** calls `sandbox.run_code` with timeout + memory cap. Captures the computed table or the traceback. Never sets `error` on a code error (that's the retry loop's job); sets `error` only on sandbox-infrastructure failure.

### `answer`
**Reads:** `question`, `result_table`. **Writes:** `answer`, `key_numbers`, a chart hint (into `exec_result`/state), `tokens`, `step_trace`.
**LLM:** yes — `gemini-3.5-flash`, prompt `src/prompts/answer.md`; input is the question + the **computed result table** (not raw data); output is strict JSON `{answer, key_numbers, chart}`.
**External calls:** Gemini (as above). On JSON parse failure → one reformat retry → else `error`.

### `build_chart`
**Reads:** chart hint, `result_table`. **Writes:** `chart_spec`.
**LLM:** no. **Behaviour:** deterministically builds a Plotly figure spec (`src/charts/spec.py`) from the hint (`type` ∈ bar|line|scatter|pie) + the result table; falls back to a table-only spec if the shape can't be charted. Never fails the run.

### `finalize`
**Reads:** all output fields. **Writes:** `status="completed"`. **Behaviour:** persists the full audit record to SQLite (`RunRow`) and appends a JSON line to `data/audit.log`; emits a structlog line (question, latency, tokens, status).

### `handle_error`
**Reads:** `error`, `run_id`, `step_trace`. **Writes:** `status="failed"`. **Behaviour:** persists the failed run + trace to SQLite + audit log, logs with `run_id`, terminates.

---

## Graph / Flow Topology

```
START
  │
  ▼
prepare ──(error)──────────────────────────► handle_error ──► END
  │
  ▼
write_code ──(error)───────────────────────► handle_error
  │
  ▼
execute
  │
  ├─(ok)──────────────────────► answer ──(error)──► handle_error
  │                                │
  ├─(code error, attempt<max)──► write_code   │(ok)
  │        (retry with traceback)              ▼
  └─(code error, attempt>=max)─► handle_error  build_chart
                                                │
                                                ▼
                                             finalize ──► END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| `prepare` | `state.error` set | `handle_error` |
| `prepare` | else | `write_code` |
| `write_code` | `state.error` set (Gemini hard failure) | `handle_error` |
| `write_code` | else | `execute` |
| `execute` | `exec_result.ok` | `answer` |
| `execute` | `not ok` and `attempt < max_steps` | `write_code` |
| `execute` | `not ok` and `attempt >= max_steps` | `handle_error` |
| `answer` | `state.error` set | `handle_error` |
| `answer` | else | `build_chart` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state | schema, samples, code, exec results, trace, tokens |
| **Across runs** | SQLite `runs` + `data/audit.log` | full audit trail (question, code, result, tokens, steps, status) |
| **Loaded dataset** | Dataset store (parquet on disk, referenced by `dataset_id`) | dataset stays loaded across questions without re-upload (Phase 1) |
| **Conversation** | Phase 2 — `SessionRow` + `MessageRow` message history injected into `write_code` | multi-turn follow-ups ("now break that down by month") |

> **Assumed / justified:** multi-turn conversation memory is **deferred to Phase 2**, because the brief scopes Phase 1 to a single question (upload → ask ONE → answer) as the smallest first-time-right win. The dataset still stays loaded in Phase 1; only the multi-turn history browser and follow-up context are Phase 2. This is an explicit, intentional deferral, not a gap.

**Context-window management:** trivially bounded — only schema + ≤ `sample_rows` rows + one result table are ever sent; no full data, no growth with dataset size.

---

## Human-in-the-Loop Checkpoints

Phase 1–2: none. **Phase 3** adds the clarification gate:

| Checkpoint | What is shown | Expected user action | Timeout / default |
|------------|---------------|----------------------|-------------------|
| `clarify` (Phase 3) | One clarifying question when the ask is genuinely ambiguous | User types a short reply | No timeout; the run waits for the reply, then resumes at `write_code` |

---

## Error Handling & Recovery

**Node-level:** each node try/excepts; a fatal error sets `state["error"]` and routing sends it to `handle_error`. Code errors are NOT fatal — they drive the bounded retry loop.

**Graph-level (`handle_error`):** reads `state.error`, `run_id`, `step_trace`; updates the `RunRow` → status `failed`, `error_message`, `completed_at`; appends to `data/audit.log`; logs with `run_id`; terminates.

**Resume / retry strategy:** the write→execute cycle retries up to `max_steps` (default 3) with the traceback fed back. No cross-invocation resume (runs are short); a failed run is simply re-asked.

**Partial failure:** if `build_chart` cannot chart the result shape, it degrades to a table-only spec and the run still completes with the prose answer + table — the chart is optional, the answer is not.

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | One structured log line per run; one `step_trace` entry per node | structlog → stdout + `step_trace_json` in SQLite (LangSmith optional/off) |
| **LLM calls** | Prompt/completion/total tokens, latency, model per call | structlog + `tokens` accumulated in state → `RunRow` |
| **Tool calls** | Sandbox code, ok/error, duration_ms | `step_trace` + `data/audit.log` |
| **Run outcome** | Status, total duration, error | SQLite `RunRow` + structlog |

---

## Concurrency Model

- **Run isolation:** one run at a time is the expected personal-use pattern; runs are scoped by `run_id` and the sandbox is a fresh subprocess per run, so concurrent runs are naturally isolated (no shared mutable in-process df).
- **Parallel nodes within a run:** none — the loop is inherently sequential.
- **Checkpointing:** none (runs are short; no human-in-the-loop until Phase 3, where the clarify node uses a LangGraph interrupt).

---

## Graph Assembly (`src/graph/agent.py`)

```python
graph = StateGraph(AgentState)

graph.add_node("prepare", prepare)
graph.add_node("write_code", write_code)
graph.add_node("execute", execute)
graph.add_node("answer", answer)
graph.add_node("build_chart", build_chart)
graph.add_node("finalize", finalize)
graph.add_node("handle_error", handle_error)

graph.set_entry_point("prepare")

graph.add_conditional_edges(
    "prepare",
    lambda s: "handle_error" if s.get("error") else "write_code",
    {"handle_error": "handle_error", "write_code": "write_code"},
)
graph.add_conditional_edges(
    "write_code",
    lambda s: "handle_error" if s.get("error") else "execute",
    {"handle_error": "handle_error", "execute": "execute"},
)
graph.add_conditional_edges(
    "execute",
    route_after_execute,  # ok→answer | (not ok & attempt<max)→write_code | else→handle_error
    {"answer": "answer", "write_code": "write_code", "handle_error": "handle_error"},
)
graph.add_conditional_edges(
    "answer",
    lambda s: "handle_error" if s.get("error") else "build_chart",
    {"handle_error": "handle_error", "build_chart": "build_chart"},
)
graph.add_edge("build_chart", "finalize")
graph.add_edge("finalize", END)
graph.add_edge("handle_error", END)

compiled_graph = graph.compile()
```
