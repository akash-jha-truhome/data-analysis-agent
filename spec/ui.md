# UI

Single-page web app (Next.js 15 static export) served at `http://localhost:8001/app/`. One screen; Phase 1 delivers the full upload → ask → answer path for real, with deferred features as clearly-labelled non-functional stubs.

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

**Key elements (Phase 1 — LABELLED STUBS, non-functional, visually distinct/greyed with a "coming soon" tag):**
- "Ask a follow-up" hint under the answer (memory) — Phase 2.
- "Suggested questions" chip row placeholder — Phase 2.
- "Data-quality flags" banner slot — Phase 2.
- "Session history" side panel + session **token-total** badge — Phase 2.
- "Add another file / sheet" control near upload — Phase 3.

**Actions available (Phase 1):** upload a file; ask a question; toggle chart/table; expand/collapse the code + trace.

## Error States

- **Upload error** (400/500) → inline red banner on the dropzone ("Couldn't read that CSV — …"), file cleared, retry enabled.
- **Ask error** (422 no runnable code / 500) → red answer-panel banner with `error.message`; **no chart, no fabricated numbers**; the "Code it ran" block still shows the attempts so the user sees what was tried.
- **Loading** → the live step indicator (spinner + current step); Ask button disabled while in flight.
- **Empty state** → before upload, a hint ("Upload a CSV to get started"); after upload but before asking, ("Ask a question about your data").
- **Network error** → "Network error — is the server running on :8001?"

## Tech Stack

Next.js 15 + React 19 + Tailwind CSS, static export (`output: 'export'`). Charts: `react-plotly.js` + `plotly.js-dist-min`. API calls via `frontend/src/lib/api.ts` (same-origin fetch). E2E: Playwright in `frontend/tests/e2e/` against the live app.
