# Capability: Answer Question (code-execution loop)

## What It Does
Turns a natural-language question into real pandas code, runs it in a bounded sandbox against the full dataset, retries on error, and returns a plain-language answer with the actually-computed key numbers.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id | string | `POST /ask` | yes |
| question | string | `POST /ask` | yes |
| schema + sample_rows | derived | Dataset store (loaded in `prepare`) | yes (LLM-visible) |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| answer | string (prose) | API response → answer panel |
| key_numbers | `[{label, value}]` | API response → stat chips |
| result_table | `{columns, rows}` | API response + `runs.result_json` |
| generated_code | string | API response + `runs.generated_code` |
| step_trace | `[{step, action, code, ok, error, duration_ms}]` | API response + `runs.step_trace_json` |
| tokens | `{prompt, completion, total}` | API response + `runs.*_tokens` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini Flash (`gemini-3.1-flash`) | `write_code`, then `answer` | Transient → retry/backoff; hard → `handle_error`, run `failed`, clean `api_error` — never a fabricated number |
| Sandbox subprocess | Execute generated pandas on full data | Code error → feed traceback back, retry (bounded `max_steps`); infra error → `handle_error` |

## Business Rules
- The LLM receives ONLY schema + ≤ `sample_rows` rows (+ prior code + traceback on retry) — never the full dataset.
- Numbers are computed by executed pandas on the FULL dataset, not by the LLM.
- Retry is bounded to `AGENT_MAX_STEPS` (default 3) attempts; after that, surface a clean failure.
- The `answer` step composes prose from the computed result table only.

## Success Criteria
- [ ] For a fixture CSV of ≥ 50,000 rows, a groupby/sum question returns the value computed over ALL rows — provably different from any value derivable from the 5 sample rows.
- [ ] The assembled `write_code` prompt contains ≤ `sample_rows` data rows (asserted).
- [ ] A deliberately hard question that first produces erroring code recovers via the traceback-retry loop and still answers within `max_steps`.
- [ ] When code can't be produced within `max_steps`, the response is `status:"failed"` with `answer:null` and a message — no fabricated number.
- [ ] Every successful run persists exactly 2 LLM calls' worth of tokens (write_code + answer) plus any retry.
