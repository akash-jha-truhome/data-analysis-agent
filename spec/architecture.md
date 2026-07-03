# Architecture

System design for the local CSV/Excel data-analysis agent. HOW lives here and in `spec/agent.md`; the product narrative lives in `roadmap.md`, `capabilities/`, `data.md`, `api.md`, `ui.md`.

---

## System Overview

A single-user, local web application. A FastAPI backend serves both a REST API and the statically-exported Next.js frontend at `/app` on port **8001**. The user uploads a spreadsheet; the backend loads it with pandas, extracts a schema + a few sample rows, and persists the file locally. When the user asks a question, a **LangGraph agent** (Gemini Flash) writes real pandas code from the schema + sample rows only, runs it in a **bounded, network-free subprocess against the full dataframe**, observes the result (retrying with the traceback on error, bounded), then produces a plain-language answer, key numbers, and a chart specification. Every query is persisted to SQLite and a local audit log. Raw data and code execution never leave the machine, and the LLM never sees the full dataset.

## Component Map

```
Browser (Next.js static export at /app)
    │  POST /datasets (multipart)  ·  POST /ask  ·  GET /runs/{id}
    ▼
FastAPI (src/api)
    │
    ├─► Dataset store (src/datasets)  ──►  data/datasets/<id>/{original.csv, data.parquet}
    │
    └─► Graph runner (src/graph/runner.py)
            │
            ▼
        LangGraph agent (src/graph/agent.py)
            prepare → write_code → execute → answer → build_chart → finalize
                          ▲   │ (error, bounded retry)
                          └───┘
            │                       │                         │
            ▼                       ▼                         ▼
      Gemini Flash          Sandbox executor           Audit trail
      (src/llm)             (src/sandbox, subprocess)   (SQLite runs + data/audit.log)
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| **API** (`src/api`) | HTTP surface: upload, ask, fetch run/audit. Validates input, returns `ok(data)` / `api_error`. |
| **Dataset store** (`src/datasets`) | Persist uploads locally, load with pandas, normalize to parquet, extract schema + sample rows. |
| **Agent** (`src/graph`) | LangGraph loop: write pandas → execute → observe/retry → answer + chart spec. |
| **Sandbox** (`src/sandbox`) | Run generated pandas in a bounded, network-free subprocess; capture result or traceback. |
| **LLM** (`src/llm`) | Gemini Flash provider + client; token accounting. |
| **Charts** (`src/charts`) | Deterministically build a Plotly figure spec from the answer node's structured chart hint + result table. |
| **Observability** (`src/obs`) | Structured stdout logging + append-only local audit log file. |
| **Storage** | SQLite (`data/agent.db`) for the audit trail; local filesystem for datasets. |

## Data Flow

1. **Trigger:** user uploads a CSV/Excel via the browser → `POST /datasets`.
2. Backend saves the original locally, loads it with pandas, writes a normalized `data.parquet`, extracts `{columns:[{name,dtype}], n_rows, n_cols}` + `sample_rows` (default 5), persists a `DatasetRow`, returns the metadata + sample rows.
3. User asks a question → `POST /ask {dataset_id, question}`. The runner creates a `RunRow` and invokes the graph.
4. `prepare` loads the dataset's schema + sample rows into agent state (full data NOT loaded here).
5. `write_code` (Gemini Flash) receives **only** schema + sample rows + question (+ traceback on retry) and returns a brief plan + pandas code that assigns a `result` variable.
6. `execute` runs the code in the sandbox subprocess with the full dataframe loaded from parquet, a wall-clock timeout, and a memory cap; captures `result` (scalar/Series/DataFrame → normalized table) or an error+traceback.
7. On error and `attempt < max_steps`, loop back to `write_code` with the traceback; otherwise `handle_error`.
8. `answer` (Gemini Flash) receives the question + the **computed result table** (not the raw data) and returns structured JSON: prose answer, key numbers, and a chart hint (`type`, `x`, `y`, `series`).
9. `build_chart` deterministically assembles a Plotly figure spec from the chart hint + result table.
10. `finalize` persists the full audit record (question, code, result, tokens, step trace, status) to SQLite and appends to `data/audit.log`.
11. **Output:** the API returns `{run_id, answer, key_numbers, chart, table, code, steps, tokens, status}`; the browser renders answer + interactive chart + table toggle + collapsible code.

## Sandboxed Execution Model

Generated pandas is **never** `exec`'d in the API process. `src/sandbox/executor.py` exposes:

```python
def run_code(code: str, parquet_paths: dict[str, str], *, timeout_s: int, mem_mb: int) -> ExecResult
# ExecResult: {ok: bool, result_table: dict|None, result_repr: str|None,
#              stdout: str, error: str|None, traceback: str|None, duration_ms: int}
```

It spawns a child: `subprocess.run([sys.executable, "-m", "sandbox.runner"], input=<json>, timeout=timeout_s, capture_output=True, cwd=<repo>, env=<minimal>)`. The child (`src/sandbox/runner.py`):

- Sets `resource.setrlimit(RLIMIT_AS, mem_mb*MB)` and `RLIMIT_CPU` before doing work (POSIX; on non-POSIX the parent `timeout` is the guard — documented).
- Loads each parquet into a dataframe (`df` for the single-file case; named frames for multi-file in Phase 3).
- Executes the generated code in a restricted namespace exposing only `pd`, `np`, and the dataframe(s) — no `open`, no `__import__` of network libs; the code is expected to assign `result`.
- Normalizes `result` (scalar → `{value}`; Series/DataFrame → `{columns, rows}` capped at `max_result_rows`, default 1000) and prints a JSON envelope to stdout.

**Timeout** (`AGENT_SANDBOX_TIMEOUT_S`, default 25) and **memory cap** (`AGENT_SANDBOX_MEM_MB`, default 2048) are enforced. **No network:** the child performs no network calls and imports no network libraries; being a short-lived, resource-bounded separate process is the isolation boundary (full OS-level network firewalling is out of scope for a local personal tool — documented as `Assumed`). On timeout or non-zero exit, the executor returns `ok=False` with the captured traceback so the graph can retry.

## Schema + Sample-Rows-Only Contract to the LLM

The only dataframe-derived content ever sent to Gemini is:
- `schema`: column names + dtypes + `n_rows` + `n_cols`.
- `sample_rows`: at most `AGENT_SAMPLE_ROWS` (default 5) rows, taken from the head, stringified.
- On the answer step, the **computed result table** (already an aggregate, capped rows).

The full dataframe exists only inside the sandbox subprocess (loaded from parquet). A test asserts the assembled `write_code` prompt contains ≤ `sample_rows` data rows.

## Session / Dataset Persistence

- Uploaded files live under `data/datasets/<dataset_id>/` (`original.<ext>` + `data.parquet`). Referenced by `dataset_id`; the frontend keeps the id and passes it with every `/ask`, so the dataset "stays loaded" without re-upload. The sandbox reloads the parquet per run (cheap, stateless, safe).
- Phase 1: dataset stays loaded for the single-question flow. Phase 2 adds a `SessionRow` + `MessageRow` conversation history so follow-ups have context.

## Audit Trail

Two sinks, written in `finalize`:
- **SQLite** `runs` table (extended `RunRow`): `question`, `generated_code`, `result_json`, `chart_json`, `step_trace_json`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `status`, `error_message`, `dataset_id`, timestamps.
- **Local file** `data/audit.log` (append-only, one JSON line per run): timestamp, run_id, dataset_id, question, code, result summary, tokens, status.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Google Gemini API (Flash) | Write pandas code + compose the answer | Retry/backoff on transient errors; on hard failure `handle_error` sets run `failed` and the API returns a clean `api_error` — no fabricated numbers. |
| SQLite (`data/agent.db`) | Audit trail persistence | Fatal — surfaced as `api_error`; this is the production DB for the tool. |
| Local filesystem (`data/`) | Dataset + parquet + audit log storage | Fatal on write failure; surfaced as `api_error`. |

## Stack

> Concrete choices for this project. Generic rules (model-naming, DB driver, dev port, real-key tests) live in `harness/patterns/tech-stack.md`.

- **Language:** Python 3.12 (repo requires ≥ 3.11); TypeScript for the frontend.
- **Agent framework:** LangGraph (`langgraph>=0.1`) — the write→execute→observe→retry loop needs conditional edges and a bounded cycle.
- **LLM provider + model:** Google Gemini, model **`gemini-3.5-flash`** (Flash tier — cheapest sensible default; the Flash sibling of the skeleton's `gemini-3.1-pro`). Set via `AGENT_LLM_MODEL=gemini-3.5-flash`; `GeminiProvider.DEFAULT_MODEL` updated to this. Provider resolves to `gemini` (auto from `AGENT_GEMINI_API_KEY`). > **Assumed:** `gemini-3.5-flash` is the current Flash model id; confirm and adjust `AGENT_LLM_MODEL` if the live id differs.
- **Backend:** FastAPI (`fastapi>=0.115`) + uvicorn, serving the static frontend at `/app` on port 8001. Run: `uv run python -m src`.
- **Database + ORM:** SQLite (`data/agent.db`) + SQLAlchemy 2.0 + Alembic. SQLite **is the production database** for this local, single-user tool — the Phase-1 gate runs `uv run alembic upgrade head` + `uv run pytest` against it (there is no PostgreSQL here).
- **Frontend:** Next.js 15 + React 19, static export (`output: 'export'` → `frontend/out/`), Tailwind CSS. Built with `pnpm build`.
- **Charting:** **Plotly** — `react-plotly.js` + `plotly.js-dist-min`. Chosen because it gives interactive hover/zoom/pan out of the box and renders directly from a JSON figure spec, which pairs cleanly with the LLM-derived chart hint. (Recharts was the alternative; rejected because Plotly's built-in interactivity + JSON-spec model fit the auto-chart-from-spec design better.)
- **Data engine:** pandas + pyarrow (parquet) for load/normalize/execute.
- **Sandbox:** stdlib `subprocess` + `resource` rlimits (memory/CPU) + wall-clock timeout; child module `sandbox.runner`.
- **Observability:** `structlog` structured logging to stdout (input/output/latency/error per query) + append-only `data/audit.log`. LangSmith tracing is optional and OFF by default (local/private tool — no cloud); enable via `LANGCHAIN_TRACING_V2` + `LANGCHAIN_API_KEY` if desired.
- **Dependency management:** uv + `pyproject.toml` (backend); pnpm (frontend).
- **E2E testing:** Playwright (`frontend/tests/e2e/`) against the live app at `http://localhost:8001/app/`.

| Key library | Version | Purpose |
|-------------|---------|---------|
| fastapi | ≥ 0.115 | HTTP API + static mount |
| langgraph | ≥ 0.1 | Agent graph / loop |
| google-genai | ≥ 2.9 | Gemini Flash client |
| pandas | ≥ 2.2 | Load + execute analysis |
| pyarrow | ≥ 16 | Parquet read/write |
| sqlalchemy | ≥ 2.0 | ORM for audit trail |
| alembic | ≥ 1.13 | Migrations |
| structlog | ≥ 24.1 | Structured logging |
| python-multipart | ≥ 0.0.9 | Multipart file upload |
| openpyxl | ≥ 3.1 | Excel loading (Phase 3) |
| react-plotly.js / plotly.js-dist-min | latest | Interactive charts |

**Avoid:** executing generated code in the API process (must be the subprocess sandbox); sending full data to the LLM (schema + sample rows only); SQLite-as-substitute framing (SQLite is genuinely production here); any cloud storage of raw data; a hardcoded op-list interpreter instead of real generated pandas (anti-pattern from `agentic-ai.md` #22).

## Deployment Model

A local, long-running process started with `uv run python -m src` from the repo root, serving the API and the built frontend on `http://localhost:8001` (`/app/` for the UI). Single process, single user, SQLite + local files. No containers, no cloud, no auth.
