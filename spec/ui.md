# UI

Single-page web app (Next.js 15 static export) served at `http://localhost:8001/app/`. One screen. Phase 1 delivered the full upload → ask → answer path; Phase 2 turned it into a real "upload once, ask many" session (conversation thread + memory, auto-suggested follow-ups, a data-quality banner, and a run-history panel with a running session token total). Phase 3 (final) wires the last deferred features into real behaviour — multi-file upload, Excel multi-sheet sources, and an inline clarification gate. **No stub/"coming soon" placeholders remain anywhere in the UI.**

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

**Key elements (Phase 3 — REAL, wiring the former Phase-3 stubs; NO stubs remain):**
- **Multi-source uploader (`UploadPanel`)** — the single dropzone now accepts `.csv`, `.xlsx`, and `.xls`. `POST /datasets` is multipart with an optional `session_id`; the frontend sends the current `session_id` (once minted) so additional uploads attach to the same session. A CSV upload adds ONE source; an Excel upload (`is_excel:true`, `datasets:[…]`) adds ONE source PER sheet. The first upload starts a fresh session; later uploads append. The panel keeps showing the latest dataset's filename / shape / sample-row preview.
- **Loaded-source chips (`SourceChips`)** — every loaded source renders as a chip showing its `filename` (and origin workbook for Excel sheets) plus the `var_name` the user can reference in a question (e.g. `orders`, `customers`, `sales_sheet1`). With ≥2 sources a hint appears — e.g. *"join orders and customers on id"* — so cross-file questions are discoverable. Each chip has a remove control; removing the last source clears the session.
- **Multi-file question threading** — every `POST /ask` sends `dataset_id` (the primary source) plus `dataset_ids` = ALL currently-loaded source ids (and the `session_id`), so the agent can join/compare across files and Excel sheets in one question.
- **Inline clarification gate (`ClarificationBox`)** — when an `/ask` 200 response is `status:"needs_clarification"` (with `clarification:"<question>"`, `answer:null`), the agent's question renders INLINE in that thread turn with a text input + Reply button (an amber "Agent" bubble, not an error). Submitting re-POSTs `/ask` with the SAME `question` plus `clarification_answer` (+ `session_id`, `dataset_ids`); the resulting answer replaces the prompt in the same turn, so it reads as a natural back-and-forth.

**Actions available (Phase 3):** upload one or more CSV/Excel files; remove a loaded source; ask a question across all loaded sources; answer an inline clarifying question; click a suggested follow-up; start a new session; toggle chart/table; expand/collapse the code + trace; expand/dismiss the data-quality banner; open a past run from history.

## Error States

- **Upload error** (400/500, or a non-CSV/Excel file) → inline red banner on the dropzone ("Couldn't read that file — …" / "isn't a CSV or Excel file"), file cleared, retry enabled.
- **Ask error** (422 no runnable code / 500) → red answer-panel banner with `error.message`; **no chart, no fabricated numbers**; the "Code it ran" block still shows the attempts so the user sees what was tried.
- **Loading** → the live step indicator (spinner + current step); Ask button disabled while in flight.
- **Empty state** → before upload, a hint ("Upload a CSV to get started"); after upload but before asking, ("Ask a question about your data to start the conversation"). History panel shows "Ask your first question…" until a session exists.
- **Network error** → "Network error — is the server running on :8001?"
- **History/session error** → the history panel shows an inline red message if `/sessions/{id}/runs` fails; the token badge shows "—" until a total is known.
- **Reopen error** → a failed `GET /runs/{id}` appends a "Reopened" error turn rather than silently doing nothing.

## Tech Stack

Next.js 15 + React 19 + Tailwind CSS, static export (`output: 'export'`). Charts: `react-plotly.js` + `plotly.js-dist-min`. API calls via `frontend/src/lib/api.ts` (same-origin fetch). E2E: Playwright in `frontend/tests/e2e/` against the live app (`golden_path.spec.ts` for the Phase-1 journey; `session.spec.ts` for the Phase-2 upload-once-ask-many session, suggestions, data-quality banner, history + token badge, and reopen; `multifile.spec.ts` for the Phase-3 multi-file upload → source chips → cross-file join answer and the inline clarification exchange).
