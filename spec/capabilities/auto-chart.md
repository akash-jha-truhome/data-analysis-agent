# Capability: Auto Chart + Table

## What It Does
Automatically picks a chart type from the question and the computed result shape, builds an interactive Plotly figure, and exposes the summary table behind it.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| chart hint | `{type, x, y, series}` | `answer` node LLM output | yes |
| result_table | `{columns, rows}` | `execute` node computed result | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| chart_spec | Plotly figure spec `{data, layout}` | API `chart` field → interactive chart |
| table | `{columns, rows}` | API `table` field → "Show data table" toggle |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| (none) | Deterministic build from the computed table | Un-chartable shape → table-only fallback; run still completes |

## Business Rules
- Chart type ∈ {bar, line, scatter, pie}, chosen from the hint + table shape (e.g. category+measure → bar; time series → line; two measures → scatter; parts-of-whole small cardinality → pie).
- The chart is built deterministically from the already-computed table — no second data pass, no LLM number generation.
- The chart must be interactive in the browser (hover values, zoom/pan) and toggleable to the raw table.

## Success Criteria
- [ ] A groupby-sum result renders a bar chart whose bars equal the table values.
- [ ] A time-indexed result renders a line chart.
- [ ] An un-chartable result (e.g. a single scalar) degrades to a table-only view without failing the run.
- [ ] The "Show data table" toggle displays exactly the `table` rows in the response.
