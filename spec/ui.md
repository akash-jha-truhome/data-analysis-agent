# UI

Single-page web app (Next.js 15 static export) served at `http://localhost:8001/app/`. One screen. Phase 1 delivered the full upload → ask → answer path; Phase 2 turns it into a real "upload once, ask many" session (conversation thread + memory, auto-suggested follow-ups, a data-quality banner, and a run-history panel with a running session token total). Remaining deferred features ship as clearly-labelled non-functional stubs.

---

## UI Type

Web single-page app. Next.js 15 + React 19 + Tailwind CSS, static export → `frontend/out/`, mounted by FastAPI at `/app`. Interactive charts via **Plotly** (`react-plotly.js`).

## Views / Screens

### Screen: Analysis Workbench (single page)

**Purpose:** Upload a dataset, ask a question, read the computed answer + chart + code.

**Key elements (Phase 1 — REAL):**
- **Upload dropzone** — drag/drop or pick a CSV → `POST /datasets`. On success shows filename, row/column counts, and a small preview of the sample rows. The dataset id is held client-side so it "stays loaded" for subsequent questions.
- **Question box** — text input + Ask button → `POST /ask` with the held `dataset_id`.
- **Live step indicator** — spinner + step text driven by the response's `steps` and an in-flight state: "Writing code…", "Running…", "Charting…".
- **Answer panel** — the plain-language `answer` with `key_numbers` rendered as prominent stat chips.
- **Interactive chart** — Plotly figure from `chart` (hover values, zoom/pan). A **"Show data table" toggle** flips to the `table` behind the chart.
- **"Code it ran" (collapsible)** — the exact `code` plus the per-step `steps` trace (each attempt, ok/error, duration). Collapsed by default.

**Key elements (Phase 2 — REAL, wiring the former Phase-1 stubs):**
- **Conversation thread (`SessionThread`)** — the page holds a `session_id` in state. It is captured from the FIRST `/ask` response (`data.session_id`) and sent on every subsequent `/ask` (`{dataset_id, question, session_id}`), so follow-ups like "now break that down by month" work via server-side memory. Each Q&A turn renders in order — the question, then its answer/key-numbers/chart/code result (the Phase-1 `ResultView`) — so the exchange reads as a thread. The dataset stays loaded across turns. A **"New session"** button clears the thread and session while keeping the dataset loaded; loading a new dataset also starts a fresh session.
- **Auto-suggested follow-up chips (`SuggestionChips`)** — after each answer, the `data.suggestions` array (≤3) renders as clickable chips; clicking one submits it as the next question in the SAME session.
- **Data-quality banner (`DataQualityBanner`)** — renders `data.data_quality` (missing values, duplicate rows, outliers) as a dismissible banner tied to the current dataset: a concise `summary` with an expandable details view. Renders nothing when `data_quality` is null or flags nothing (never a broken box). Reset (re-shown) when a new dataset is loaded.
- **Run-history panel (`HistoryPanel`) + session token badge (`TokenBadge`)** — a side panel lists this session's past queries via `GET /sessions/{id}/runs` (question, status, tokens, timestamp), newest-first; clicking one REOPENS it via `GET /runs/{id}` and re-renders that result as a "Reopened" turn in the thread. A running **session token-total** badge shows `total_tokens` (from the same `/sessions/{id}/runs` payload), refreshed after each ask.

**Key elements (Phase 3 — LABELLED STUBS, non-functional, visually distinct/greyed with a "coming soon" tag):**
- "Add another file / sheet" control near upload (multi-file) — Phase 3.
- "Excel multi-sheet analysis" panel item — Phase 3.
- "Clarifying questions" panel item — Phase 3.

**Actions available (Phase 2):** upload a file; ask a question; click a suggested follow-up; start a new session; toggle chart/table; expand/collapse the code + trace; expand/dismiss the data-quality banner; open a past run from history.

## Error States

- **Upload error** (400/500) → inline red banner on the dropzone ("Couldn't read that CSV — …"), file cleared, retry enabled.
- **Ask error** (422 no runnable code / 500) → red answer-panel banner with `error.message`; **no chart, no fabricated numbers**; the "Code it ran" block still shows the attempts so the user sees what was tried.
- **Loading** → the live step indicator (spinner + current step); Ask button disabled while in flight.
- **Empty state** → before upload, a hint ("Upload a CSV to get started"); after upload but before asking, ("Ask a question about your data to start the conversation"). History panel shows "Ask your first question…" until a session exists.
- **Network error** → "Network error — is the server running on :8001?"
- **History/session error** → the history panel shows an inline red message if `/sessions/{id}/runs` fails; the token badge shows "—" until a total is known.
- **Reopen error** → a failed `GET /runs/{id}` appends a "Reopened" error turn rather than silently doing nothing.

## Tech Stack

Next.js 15 + React 19 + Tailwind CSS, static export (`output: 'export'`). Charts: `react-plotly.js` + `plotly.js-dist-min`. API calls via `frontend/src/lib/api.ts` (same-origin fetch). E2E: Playwright in `frontend/tests/e2e/` against the live app (`golden_path.spec.ts` for the Phase-1 journey; `session.spec.ts` for the Phase-2 upload-once-ask-many session, suggestions, data-quality banner, history + token badge, and reopen).
