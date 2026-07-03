# Data Model

The audit trail + local dataset store for the analysis agent.

---

## Storage Technology

**SQLite** (`data/agent.db`) via SQLAlchemy 2.0 + Alembic — the **production database** for this single-user local tool. Uploaded datasets live on the **local filesystem** under `data/datasets/<dataset_id>/`. A per-run **append-only audit log** is written to `data/audit.log`. Nothing goes to the cloud.

## Entities

### Entity: RunRow (`runs`) — extended from the skeleton

One row per question asked. This is the audit trail: exactly what was asked, the code that ran, what it returned, and the cost.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (`run_id`) |
| dataset_id | Text | yes (P1) | FK → `datasets.id`; the dataset queried |
| session_id | Text | no | FK → `sessions.id` (Phase 2); null in Phase 1 |
| question | Text | yes | The user's natural-language question |
| generated_code | Text | no | The final pandas code that produced the answer |
| result_json | Text (JSON) | no | Normalized result table `{columns, rows}` behind the answer |
| answer_text | Text | no | Final plain-language answer |
| key_numbers_json | Text (JSON) | no | `[{label, value}]` |
| suggestions_json | Text (JSON) | no | Phase 2 — `["q1","q2","q3"]` follow-up questions (batched into `answer`) |
| data_quality_json | Text (JSON) | no | Phase 2 — `{missing:[{column,count,pct}], duplicate_rows, outliers:[{column,count}], summary}` from `profile_quality` |
| chart_json | Text (JSON) | no | Plotly figure spec |
| step_trace_json | Text (JSON) | no | `[{step, action, code, ok, error, duration_ms}]` — every attempt |
| prompt_tokens | Integer | no | Sum of prompt tokens across LLM calls |
| completion_tokens | Integer | no | Sum of completion tokens |
| total_tokens | Integer | no | prompt + completion |
| status | Text | yes | `pending` \| `completed` \| `failed` |
| error_message | Text | no | Set when `status=failed` |
| created_at | Timestamp | yes | Insert time |
| updated_at | Timestamp | yes | Last update |

> Skeleton compatibility: the existing `input_text`/`output_text` columns are retained (nullable) or migrated; the analysis columns are added in `alembic/versions/0002_*.py`. The Phase 2 insight columns (`suggestions_json`, `data_quality_json`) plus the `sessions` + `messages` tables are added in `alembic/versions/0003_sessions_and_insights.py` (SQLite-safe `op.batch_alter_table` for the new `runs` columns).

### Entity: DatasetRow (`datasets`)

One row per uploaded file (its local storage + schema).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (`dataset_id`) |
| filename | Text | yes | Original uploaded filename |
| storage_path | Text | yes | `data/datasets/<id>/original.<ext>` |
| parquet_path | Text | yes | `data/datasets/<id>/data.parquet` (normalized, for the sandbox) |
| n_rows | Integer | yes | Row count of the full dataset |
| n_cols | Integer | yes | Column count |
| schema_json | Text (JSON) | yes | `[{name, dtype}]` |
| sample_rows_json | Text (JSON) | yes | ≤ `sample_rows` rows shown to the LLM |
| created_at | Timestamp | yes | Upload time |

### Entity: SessionRow (`sessions`) — Phase 2

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key (`session_id`) |
| dataset_id | Text | yes | Currently loaded dataset (Phase 3: many via join table) |
| total_tokens | Integer | yes | Running session token total |
| created_at | Timestamp | yes | Session start |

### Entity: MessageRow (`messages`) — Phase 2

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| session_id | Text | yes | FK → `sessions.id` |
| run_id | Text | no | FK → `runs.id` (assistant turns) |
| role | Text | yes | `user` \| `assistant` |
| content | Text | yes | Turn content (question or answer summary) |
| created_at | Timestamp | yes | Turn time |

### Entity: SessionDatasetRow (`session_datasets`) — Phase 3 (multi-file)

Join table linking datasets to a session so one session may analyse multiple
datasets at once (multiple CSVs, or one dataset per Excel sheet).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | Text (uuid) | yes | Primary key |
| session_id | Text | yes | FK → `sessions.id` |
| dataset_id | Text | yes | FK → `datasets.id` |
| var_name | Text | yes | Python variable the dataframe is exposed as in the sandbox/prompt |
| created_at | Timestamp | yes | Link creation time (defines ordering) |

Unique constraint on (`session_id`, `dataset_id`).

**var_name convention:** the FIRST dataset linked to a session is exposed as
`df` (preserving single-file behavior + the deterministic quality script that
references `df`). Subsequent datasets get a lowercase python identifier
sanitized from their filename/sheet name (e.g. `orders_2024`), deduplicated
within the session by appending `_2`, `_3`, … on collision.

**Excel multi-sheet ingestion:** an uploaded `.xlsx`/`.xls` workbook produces
one `DatasetRow` per non-empty sheet. Each sheet's `filename` is recorded as
`"<workbook>#<SheetName>"`, gets its own `data.parquet`, schema, and ≤5 sample
rows, and its `var_name` is sanitized from the sheet name (deduped within the
workbook). A workbook with no readable sheet/rows is a 400.

### Relationships

- `DatasetRow` 1—N `RunRow` (a dataset is queried by many runs).
- `SessionRow` 1—N `RunRow` and 1—N `MessageRow` (Phase 2).
- `SessionRow` N—N `DatasetRow` via a join table (Phase 3 multi-file).

## Data Lifecycle

- **Create:** `DatasetRow` + local files on upload; `RunRow` on each `/ask`.
- **Update:** `RunRow` progresses `pending → completed|failed` in `finalize`/`handle_error`.
- **Delete:** manual only — the user deletes `data/datasets/<id>/` and/or clears `data/agent.db`. No automatic retention/TTL (personal tool). `data/audit.log` grows append-only until the user rotates it.

## Sensitive Data

The uploaded data may contain personal/business content, so it is treated as sensitive-by-default: it **never leaves the machine**, and the **LLM only ever receives schema + ≤ `sample_rows` sample rows** (plus computed aggregate result tables) — never the full dataset. There are no secrets in the DB except nothing (API keys live only in `.env`, never persisted). No auth/PII handling beyond local-only isolation, which is acceptable for a single-user local tool.
