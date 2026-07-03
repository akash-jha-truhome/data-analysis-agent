# Roadmap

Personal, browser-based CSV/Excel data-analysis agent that answers plain-English questions by writing and running REAL pandas code on the uploaded data.

---

## What This Agent Does

A single user opens a local web app, uploads a CSV (or Excel) file, and asks questions in plain English ("what were total sales by region last quarter?"). A Gemini-Flash-powered LangGraph agent inspects the file's schema and a handful of sample rows, **writes real pandas code, executes it in a bounded local subprocess against the full dataset**, and returns a plain-language answer with the key numbers, an auto-picked interactive chart, and the summary table behind it. The generated code and each step it tried are shown (collapsible) so the user can trust the numbers. Everything — the raw file and the code execution — stays on the local machine; the LLM only ever sees the schema and a few sample rows, never the full dataset.

## Who Uses It

The owner of the machine, using it ad hoc for personal data exploration. One user, one session at a time, no auth, no multi-tenant concerns. They are comfortable enough to read a formula/code block but want plain-English answers and charts, not to write pandas themselves. They **act on the numbers**, so correctness and an audit trail matter.

## Core Problem Being Solved

Answering ad-hoc questions about a spreadsheet today means either writing pandas/SQL by hand or clicking through pivot tables — slow and error-prone. Asking a plain LLM is unsafe because it hallucinates numbers. This agent closes that gap: natural-language questions in, **actually-computed** answers out (code runs on the real data), with the code and steps visible for trust, and the data never leaving the machine.

## Success Criteria

- [ ] A user can upload a CSV and get a correct, plain-language answer with key numbers to a natural-language question in under ~30 s on files up to ~100 MB.
- [ ] Reported numbers are **computed by executed pandas on the full dataset** — verified by a gate whose fixture is large enough that an answer derived only from the sample rows shown to the LLM would be wrong (sample-sum != full-sum).
- [ ] The LLM prompt payload for any query contains only the schema and at most `sample_rows` rows (default 5) — never the full dataset (asserted in a test).
- [ ] Every question renders an auto-picked interactive chart (hover/zoom/pan) plus a toggle to the summary table, and the exact generated code is viewable (collapsible).
- [ ] Every query is persisted to the SQLite audit trail (question, generated code, result, token counts, per-step trace, status) **and** appended to a local audit log file.
- [ ] The agent recovers from bad generated code: on a pandas error it feeds the traceback back and retries with a different approach, bounded to `max_steps` attempts, before surfacing a clean error.

## What This Agent Does NOT Do (Out of Scope)

- No cloud storage or remote execution — raw files and pandas execution never leave the machine.
- The LLM never sees the full dataset — only schema + a few sample rows.
- No multi-user, auth, sharing, or hosting — it is a single-user local tool.
- No arbitrary shell/network access from generated code — the sandbox exposes only `pandas`, `numpy`, and the loaded dataframe.
- Phase 1 only: no multi-file joins, no multi-sheet Excel, no clarifying-question gate, no follow-up suggestions, no data-quality flags, no multi-turn conversation memory, no run-history browser (all present as clearly-labelled stubs — see Phases).
- Not a general BI dashboard or scheduled/reporting tool — it is interactive, on-demand, ad hoc.

## Key Constraints

- **Local-only.** Data and execution stay on the machine; nothing to cloud storage. SQLite is the production database for this tool.
- **Low LLM cost.** Gemini Flash only; minimize calls (2 LLM calls per successful query — write-code + answer — plus 1 per retry).
- **Schema + sample-rows-only contract to the LLM.** Column names/types, shape, and ≤ `sample_rows` rows — never the full data.
- **Latency/scale.** CSVs up to ~100 MB; answers within ~30 s; small files snappy.
- **Bounded, sandboxed execution.** Generated pandas runs in a subprocess with a wall-clock timeout and a memory cap, no network, no filesystem writes outside a temp scratch.
- **Auditable.** Keep an exact record of the code that ran and the result it returned, in SQLite and a local log file.

## Phases of Development

> **Phase 1 is the smallest first-time-right user-testable win:** upload one CSV → ask ONE question → the agentic write-code → run → observe → answer loop returns a real answer + key numbers + an interactive chart, with the generated code visible. Everything else ships as clearly-labelled non-functional stubs.

### Phase 1 — Upload → Ask → Answer + Chart (the code-execution loop)

- **Goal:** The user uploads a real CSV, types one natural-language question, and gets back a correct plain-language answer with key numbers, an auto-picked interactive chart, the summary table behind it, and the exact pandas code that ran (collapsible) — computed end-to-end by executed pandas on the full file via the real Gemini Flash API. Bounded retry-on-error is IN scope (core correctness).
- **Independent slices (parallel build units):**
  - `slice-sandbox` (backend) — the bounded, network-free pandas execution subprocess: takes generated code + a dataframe reference, runs it with a wall-clock timeout and memory cap, captures the result table / scalar / error+traceback, returns a structured envelope. **deps: none.** Fixed contract in `spec/architecture.md` → "Sandboxed Execution Model" so other slices build against it concurrently; integrate at the gate.
  - `slice-data` (backend) — dataset ingestion + audit persistence: CSV upload → pandas load → schema + sample-row extraction, local dataset store (`data/datasets/…`), extended `runs` table + `datasets` table + Alembic migration, local audit-log-file writer, structured (structlog) request/response logging. **deps: none.** Contract in `spec/data.md`.
  - `slice-agent-api` (backend) — Gemini-Flash rewire (provider default → Flash id, settings), the LangGraph graph (state, `prepare`/`write_code`/`execute`/`answer`/`build_chart`/`finalize`/`handle_error` nodes, bounded retry loop), prompts, deterministic chart-spec builder, FastAPI `/datasets` + `/ask` + `/runs/{id}` endpoints, runner. **deps (contract-only, build concurrently):** calls `slice-sandbox`'s executor and `slice-data`'s dataset store via the interfaces fixed in the spec; wired together at the gate.
  - `slice-frontend` (frontend) — single-page UI: upload dropzone, question box, answer + key-numbers panel, interactive Plotly chart with data-table toggle, collapsible "code it ran" + step trace, spinner/live step states, and clearly-labelled stubs for all deferred features. **deps: none** (builds against `spec/api.md`).
- **Key surfaces / files:**
  - `slice-sandbox`: `src/sandbox/executor.py`, `src/sandbox/runner.py` (child process entry), `tests/test_sandbox.py`.
  - `slice-data`: `src/datasets/store.py`, `src/datasets/loader.py`, `src/db/models.py` (extend `RunRow`, add `DatasetRow`), `alembic/versions/0002_*.py`, `src/obs/audit_log.py`, `src/obs/logging.py`, `tests/test_datasets.py`.
  - `slice-agent-api`: `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/graph/runner.py`, `src/charts/spec.py`, `src/prompts/write_code.md`, `src/prompts/answer.md`, `src/llm/providers/gemini.py`, `src/config/settings.py`, `src/api/datasets.py`, `src/api/ask.py`, `src/api/runs.py`, `src/domain/*.py`, `tests/test_agent_e2e.py` (real Gemini Flash).
  - `slice-frontend`: `frontend/src/app/page.tsx`, `frontend/src/components/*`, `frontend/src/lib/api.ts`, `frontend/tests/e2e/golden_path.spec.ts`.
- **Gate command (all must pass, in order):**
  ```
  uv run alembic upgrade head \
    && uv run pytest \
    && (cd frontend && pnpm build) \
    && uv run python -m src &  # boots on :8001; serves /app
  # then, against the live app + real Gemini Flash:
  (cd frontend && pnpm exec playwright test tests/e2e/golden_path.spec.ts)
  ```
  Runs against the real Gemini Flash API (key from `.env`) and the real production DB (SQLite — the production DB for this local tool). The `test_agent_e2e.py` golden test uses a fixture CSV of ≥ 50,000 rows where the correct groupby/sum over the full data is provably different from any value derivable from the 5 sample rows shown to the LLM.
- **How the user tests it (handoff seed):**
  1. Ensure `.env` has `AGENT_GEMINI_API_KEY=…`. Build the frontend: `cd frontend && pnpm build`. Start: `uv run python -m src`. Open **http://localhost:8001/app/**.
  2. Drag a CSV onto the upload area. The app shows filename, row/column counts, and a few sample rows (REAL).
  3. Type one question (e.g. "total revenue by region") and submit. Watch the live steps ("Writing code…", "Running…", "Charting…") (REAL).
  4. Expect: a plain-language answer with key numbers, an interactive chart (hover/zoom), a "Show data table" toggle, and a collapsible "Code it ran" block with the actual pandas + step trace (all REAL).
  5. **Labelled stubs (must look intentional, not broken):** a greyed "Ask a follow-up" hint, a "Suggested questions" placeholder, a "Data-quality flags" placeholder, an "Add another file / sheet" control, a "Session history" panel, and a session token-total badge marked "coming soon". None are wired in Phase 1.

### Phase 2 — Sessions + Suggestions + Data Quality (upload once, ask many)

- **Goal:** Turn the single-shot into a real "upload once, ask many" session: the dataset stays loaded, follow-ups like "now break that down by month" work via conversation memory, each answer suggests 2–3 follow-up questions, data-quality issues noticed while answering are flagged, and a run-history panel with a running session token total appears. Wires the Phase-1 memory/suggestions/quality/history stubs.
- **Capabilities delivered (≥ 3):** `session-memory` (multi-turn conversation history + persistent loaded dataset), `follow-up-suggestions`, `data-quality-flags`, `run-history-browser` (with session token totals).
- **Independent slices (parallel build units):**
  - `slice-memory` (backend) — conversation-history in agent state + persistence, session model, follow-up-context injection into prompts. Owns `src/graph/state.py` memory fields, `src/graph/nodes.py` (context assembly), `src/db/models.py` (`SessionRow`, `MessageRow`), `alembic/versions/0003_*.py`. **deps: none.**
  - `slice-insights` (backend) — follow-up-suggestion node + data-quality profiling node/tool (missing values, duplicates, outliers computed in the sandbox). Owns `src/graph/nodes.py` (suggestion + quality nodes on disjoint functions), `src/insights/quality.py`, `src/prompts/suggest.md`. **dep:** consumes `slice-memory` state fields (contract fixed in `spec/agent.md`; build concurrently, integrate at gate).
  - `slice-history-api` (backend) — `/sessions`, `/sessions/{id}/runs`, session token-total aggregation endpoints. Owns `src/api/sessions.py`, `src/domain/session.py`. **deps: none** (reads DB shapes fixed in `spec/data.md`).
  - `slice-frontend` (frontend) — wire the memory thread, suggestion chips, data-quality banner, and run-history panel + session token badge. Owns `frontend/src/components/*`, `frontend/tests/e2e/session.spec.ts`. **deps: none** (against `spec/api.md`).
- **Key surfaces / files:** as listed per slice above.
- **Gate command:** `uv run pytest && (cd frontend && pnpm build) && (cd frontend && pnpm exec playwright test tests/e2e/session.spec.ts)` — real Gemini Flash, real SQLite; the session test asks a question then a context-dependent follow-up ("now break that down by month") and asserts the follow-up answer uses the prior turn's frame.
- **How the user tests it (handoff seed):** Upload once, ask a question, then ask a follow-up that only makes sense given the first ("now split that by month") — it works without re-stating context. See 2–3 suggested follow-up chips, click one, get an answer. See a data-quality banner when the file has missing values/duplicates. Open the history panel to see prior queries and the running session token total.

### Phase 3 — Multi-file + Excel Sheets + Clarification (richer inputs)

- **Goal:** Support real multi-source analysis: upload/keep multiple files and reference several sheets in one Excel workbook, join/compare across them in a single question, and when a question is genuinely ambiguous the agent asks one clarifying question before computing. Wires the Phase-1 "add another file / sheet" stub.
- **Capabilities delivered (≥ 3):** `multi-file-analysis` (join/compare loaded files), `excel-multi-sheet` (load + reference multiple sheets), `clarification-gate` (ask-one-question-when-ambiguous, human-in-the-loop).
- **Independent slices (parallel build units):**
  - `slice-multi-data` (backend) — multi-dataset session store, Excel workbook loader (all sheets → named dataframes), schema/sample extraction per source. Owns `src/datasets/loader.py` (Excel path), `src/datasets/store.py` (multi-ref), `src/db/models.py` (dataset↔session join). **deps: none.**
  - `slice-multi-graph` (backend) — sandbox executor accepts multiple named dataframes; `write_code`/`answer` prompts reference multiple sources; clarification node + conditional edge (pause → ask). Owns `src/sandbox/executor.py` (multi-df), `src/graph/nodes.py` (clarify node), `src/graph/edges.py`, `src/prompts/*`. **dep:** consumes `slice-multi-data`'s multi-source contract (fixed in spec; integrate at gate).
  - `slice-frontend` (frontend) — multi-file/sheet picker, source chips, clarifying-question inline prompt + answer flow. Owns `frontend/src/components/*`, `frontend/tests/e2e/multifile.spec.ts`. **deps: none.**
- **Key surfaces / files:** as above.
- **Gate command:** `uv run pytest && (cd frontend && pnpm build) && (cd frontend && pnpm exec playwright test tests/e2e/multifile.spec.ts)` — real Gemini Flash, real SQLite; the test uploads two CSVs, asks a cross-file join question, and asserts the answer is computed across both; and asks an ambiguous question and asserts the clarifying-question path fires.
- **How the user tests it (handoff seed):** Upload two related CSVs (or one multi-sheet Excel), ask a question that spans both ("compare average order value between the 2023 and 2024 files") — get one computed answer. Ask a deliberately ambiguous question and confirm the agent asks one clarifying question, then answers after you reply.
