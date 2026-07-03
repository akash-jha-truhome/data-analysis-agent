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

### `GET /sessions/{session_id}/runs`  ·  `GET /sessions/{session_id}`  *(Phase 2)*

Run-history browser + running session token total. `data` = `{session_id, total_tokens, runs:[…]}`.

## Authentication

None — local single-user tool, same-origin frontend. Binding to `0.0.0.0:8001` is inherited from the skeleton; > **Assumed:** acceptable for local use. If the machine is on an untrusted network, bind to `127.0.0.1` (a one-line change in `src/__main__.py`).
