# Capability: Audit Trail

## What It Does
Records exactly what was asked, the code that ran, what it returned, the token cost, and the per-step trace — to SQLite and a local append-only log file — so the user can trust and review every number.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| run outcome | AgentState (question, code, result, tokens, step_trace, status) | `finalize` / `handle_error` nodes | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| RunRow | DB row | SQLite `runs` table |
| audit line | JSON line | `data/audit.log` (append-only) |
| structured log | structlog event | stdout (input, output summary, latency, tokens, error) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite | Insert/update `RunRow` | Fatal → `api_error` (audit is required) |
| Local file `data/audit.log` | Append one JSON line | Log-and-continue if the log file can't be written (DB row is the source of truth) |

## Business Rules
- Every `/ask` — success OR failure — produces exactly one `RunRow` and one `data/audit.log` line.
- The stored `generated_code` is the exact code executed; `step_trace_json` includes every attempt (including erroring retries).
- Token counts are the real Gemini usage summed across all calls in the run.
- Observability (structlog line per run) is wired in Phase 1 — never deferred.

## Success Criteria
- [ ] After an `/ask`, `GET /runs/{run_id}` returns the persisted question, code, result, tokens, steps, and status.
- [ ] `data/audit.log` gains exactly one JSON line per `/ask` containing the code that ran.
- [ ] A failed run persists `status="failed"` + `error_message` and still writes an audit line.
- [ ] A structlog line with the run_id, latency, and token total appears on stdout for each run.
