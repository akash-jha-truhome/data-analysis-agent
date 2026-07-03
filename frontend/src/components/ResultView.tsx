'use client'

import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ChartView from '@/components/ChartView'
import CodeTrace from '@/components/CodeTrace'
import { Card } from '@/components/ui'
import type { AskResult, DataTable } from '@/lib/api'

export default function ResultView({ result }: { result: AskResult }) {
  return (
    <div className="space-y-4" data-testid="answer-panel">
      <Card className="p-6">
        <div className="mb-1 flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-800">Answer</h2>
        </div>

        {result.answer ? (
          <div
            data-testid="answer-text"
            className="prose prose-sm prose-slate max-w-none text-[15px] leading-relaxed text-slate-800 prose-p:my-2 prose-strong:text-slate-900"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.answer}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-sm text-slate-500">No answer was produced.</p>
        )}

        {result.key_numbers.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-3" data-testid="key-numbers">
            {result.key_numbers.map((k, i) => (
              <div
                key={`${k.label}-${i}`}
                className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5"
              >
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {k.label}
                </div>
                <div className="text-lg font-semibold tabular-nums text-slate-900">
                  {formatNumber(k.value)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {result.chart && <ChartCard chart={result.chart} table={result.table} />}

      <CodeTrace code={result.code} steps={result.steps} />
    </div>
  )
}

function ChartCard({
  chart,
  table,
}: {
  chart: NonNullable<AskResult['chart']>
  table: DataTable | null
}) {
  const [showTable, setShowTable] = useState(false)

  // When the result can't be charted (scalar / single column / non-numeric) the
  // backend sends an empty spec — render the table directly, never a blank chart.
  const notChartable = chart.table_only === true || (chart.data?.length ?? 0) === 0

  if (notChartable) {
    return (
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-800">Result</h2>
          <span className="text-xs text-slate-400">shown as a table</span>
        </div>
        {table ? (
          <DataTableView table={table} />
        ) : (
          <p className="py-6 text-center text-sm text-slate-400">
            This result is a single value — see the answer above.
          </p>
        )}
      </Card>
    )
  }

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-800">Chart</h2>
        {table && (
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-pressed={showTable}
            data-testid="toggle-table"
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
          >
            {showTable ? 'Show chart' : 'Show data table'}
          </button>
        )}
      </div>

      {showTable && table ? (
        <DataTableView table={table} />
      ) : (
        <ChartView figure={chart} />
      )}
    </Card>
  )
}

function DataTableView({ table }: { table: DataTable }) {
  if (table.columns.length === 0 || table.rows.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-400">No table data returned.</p>
  }
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-slate-200" data-testid="data-table">
      <table className="min-w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-50 text-slate-500">
          <tr>
            {table.columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 text-slate-700">
          {table.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="whitespace-nowrap px-3 py-1.5 tabular-nums">
                  {formatCell(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatNumber(v: number): string {
  if (!Number.isFinite(v)) return String(v)
  if (Number.isInteger(v)) return v.toLocaleString()
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return formatNumber(v)
  return String(v)
}
