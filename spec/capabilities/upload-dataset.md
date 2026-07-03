# Capability: Upload Dataset

## What It Does
Accepts a CSV upload, loads it with pandas, extracts a schema + a few sample rows, stores it locally, and keeps it referenced so the user can ask many questions without re-uploading.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | multipart file (CSV) | Browser upload → `POST /datasets` | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dataset metadata | `{dataset_id, filename, n_rows, n_cols, columns, sample_rows}` | API response → frontend (held for the session) |
| stored files | `original.csv` + `data.parquet` | `data/datasets/<dataset_id>/` (local only) |
| DatasetRow | DB row | SQLite `datasets` table |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Write original + parquet | 500 `api_error`; no partial dataset registered |
| pandas | `read_csv` + `to_parquet` | 400 `api_error` on unparseable/empty CSV |

## Business Rules
- Reject files over `AGENT_MAX_UPLOAD_MB` (default 100).
- `sample_rows` (default 5) rows extracted from the head; these are the ONLY data rows ever shown to the LLM.
- The full dataframe is normalized to parquet for the sandbox; it is never held in the API process beyond load.
- The dataset "stays loaded" via its `dataset_id` — no re-upload for subsequent questions.

## Success Criteria
- [ ] Uploading a valid CSV returns 200 with correct `n_rows`/`n_cols` matching the file.
- [ ] `data/datasets/<id>/data.parquet` exists and reloads to a dataframe equal to the source.
- [ ] `sample_rows` in the response contains at most `AGENT_SAMPLE_ROWS` rows.
- [ ] An unparseable or empty CSV returns 400 with a clear message and registers no dataset.
