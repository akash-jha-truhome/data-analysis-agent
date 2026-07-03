# API

REST endpoints served by FastAPI on port 8001. All responses use the skeleton envelope: success → `{"data": <payload>, "error": null}` (`ok()`); failure → HTTP error with `{"detail": {"code", "message"}}` (`api_error()`).

---

## API Style

REST + JSON, plus one multipart upload. Same-origin as the frontend (`/app`), so no CORS/auth (local single-user tool). Existing `GET /health` is unchanged.

## Endpoints / Commands

### `POST /datasets`  *(Phase 1)*

**Purpose:** Upload a CSV, load it with pandas, extract schema + sample rows, store it locally, return its id + metadata.

**Request:** `multipart/form-data` with field `file` (CSV; Excel added Phase 3).

**Response:**
```json
{
  "data": {
    "dataset_id": "uuid",
    "filename": "sales.csv",
    "n_rows": 50234,
    "n_cols": 6,
    "columns": [{"name": "region", "dtype": "object"}, {"name": "revenue", "dtype": "float64"}],
    "sample_rows": [{"region": "West", "revenue": 1200.5}]
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Missing file, unparseable CSV, empty file, or too large (> `AGENT_MAX_UPLOAD_MB`, default 100) |
| 500 | Local storage write failure |

### `POST /ask`  *(Phase 1)*

**Purpose:** Ask one natural-language question about a loaded dataset. Runs the LangGraph code-execution loop and returns the computed answer + chart + code + trace.

**Request:**
```json
{ "dataset_id": "uuid", "question": "total revenue by region" }
```
*(Phase 2 adds optional `session_id` for multi-turn context.)*

*(Phase 3 adds two optional fields:*
- *`dataset_ids: [uuid, …]` — load SEVERAL datasets into the session so a single question can join/compare across them. `dataset_id` remains the primary/anchor; when `dataset_ids` is present it supersedes it for loading (the anchor is always included). The first linked dataset is bound to the variable `df`; each additional one to a sanitized-filename variable (e.g. `customers`), which the generated pandas references by name.*
- *`clarification_answer: "…"` — the user's reply to a prior clarifying question (see below). When set, the agent writes code instead of clarifying again.)*

**Response:**
```json
{
  "data": {
    "run_id": "uuid",
    "status": "completed",
    "answer": "Total revenue was highest in the West region at $1.2M…",
    "key_numbers": [{"label": "West", "value": 1203400.0}],
    "chart": { "data": [ {"type": "bar", "x": ["West","East"], "y": [1203400, 980000]} ], "layout": {"title": "Revenue by region"} },
    "table": { "columns": ["region", "revenue"], "rows": [["West", 1203400.0]] },
    "code": "result = df.groupby('region')['revenue'].sum().reset_index()",
    "steps": [{"step": 1, "action": "write_code", "ok": true, "duration_ms": 820},
              {"step": 2, "action": "execute", "ok": true, "duration_ms": 140}],
    "tokens": {"prompt": 640, "completion": 180, "total": 820}
  },
  "error": null
}
```

*(Phase 3 adds two fields to the `data` payload on every response: `needs_clarification: bool` and `clarification: string | null`.)*

**Clarification gate *(Phase 3)*:** when a question is GENUINELY ambiguous, the agent asks ONE clarifying question BEFORE running code (the decision is folded into the existing `write_code` LLM call — no extra call). The run returns **HTTP 200** (NOT an error) with:
```json
{
  "data": {
    "run_id": "uuid",
    "session_id": "uuid",
    "status": "needs_clarification",
    "needs_clarification": true,
    "clarification": "Which metric do you mean — revenue or profit?",
    "answer": null,
    "key_numbers": [], "chart": null, "table": null,
    "code": null,
    "steps": [{"step": 1, "action": "clarify_request", "ok": true}],
    "tokens": {"prompt": 5, "completion": 3, "total": 8}
  },
  "error": null
}
```
The UI shows the question, the user replies, and the client re-issues the SAME question with `session_id` + `clarification_answer` set; that run proceeds to compute and returns `status:"completed"`. No answer/number is ever fabricated on a `needs_clarification` run.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Missing `dataset_id`/`question`, or `dataset_id` unknown |
| 422 | Agent could not produce runnable code within `max_steps` — returns `status:"failed"` with `answer:null`; `error.message` describes the failure. NEVER a fabricated number. |
| 500 | Sandbox infrastructure failure or LLM hard failure after retries |

### `GET /runs/{run_id}`  *(Phase 1)*

**Purpose:** Fetch the full audit record for a past query.

**Response:** `data` = the same shape as `/ask` plus `question`, `dataset_id`, `created_at`, and `error_message` when failed.

**Error cases:** 404 when `run_id` is unknown.

### `GET /datasets/{dataset_id}`  *(Phase 1)*

**Purpose:** Fetch stored dataset metadata (for reload/display). **Response:** `data` = the `POST /datasets` payload. **Error:** 404 unknown id.

### `GET /sessions/{session_id}`  *(Phase 2)*

**Purpose:** Session summary for the running token total + history header.

`total_tokens` is authoritative — computed as the SUM of the member runs'
`total_tokens` (robust even if the stored `SessionRow.total_tokens` counter
drifts). `run_count` is the number of runs tied to the session.

**Response:**
```json
{
  "data": {
    "session_id": "uuid",
    "dataset_id": "uuid",
    "total_tokens": 2120,
    "run_count": 2,
    "created_at": "2026-07-03T12:00:00+00:00"
  },
  "error": null
}
```

**Error cases:** 404 with `{"detail": {"code": "UNKNOWN_SESSION", "message": …}}` when `session_id` is unknown.

### `GET /sessions/{session_id}/runs`  *(Phase 2)*

**Purpose:** Run-history browser — the runs in a session, newest-first. The
frontend reopens any run via the existing `GET /runs/{run_id}`.

`total_tokens` again = the SUM of the listed runs' `total_tokens`. Each run
summary is `{run_id, question, status, total_tokens, created_at}`.

**Response:**
```json
{
  "data": {
    "session_id": "uuid",
    "dataset_id": "uuid",
    "total_tokens": 2120,
    "runs": [
      {"run_id": "uuid", "question": "revenue by region", "status": "failed", "total_tokens": 1300, "created_at": "2026-07-03T12:05:00+00:00"},
      {"run_id": "uuid", "question": "total revenue", "status": "completed", "total_tokens": 820, "created_at": "2026-07-03T12:00:00+00:00"}
    ]
  },
  "error": null
}
```

**Error cases:** 404 with `{"detail": {"code": "UNKNOWN_SESSION", "message": …}}` when `session_id` is unknown.

## Authentication

None — local single-user tool, same-origin frontend. Binding to `0.0.0.0:8001` is inherited from the skeleton; > **Assumed:** acceptable for local use. If the machine is on an untrusted network, bind to `127.0.0.1` (a one-line change in `src/__main__.py`).
