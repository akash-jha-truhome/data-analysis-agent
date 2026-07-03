'use client'

import type { Source } from '@/lib/api'
import { Card } from '@/components/ui'

/**
 * Loaded-source chips (Phase 3). Each uploaded CSV contributes one source and
 * each Excel sheet contributes its own source. A chip shows the filename and the
 * `var_name` the user can reference in a question (e.g. "join orders and
 * customers on id"). Sources can be removed individually.
 */
export default function SourceChips({
  sources,
  onRemove,
  disabled,
}: {
  sources: Source[]
  onRemove: (datasetId: string) => void
  disabled: boolean
}) {
  if (sources.length === 0) return null

  return (
    <Card className="p-5" data-testid="source-panel">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">Loaded sources</h2>
        <span className="text-xs text-slate-400">{sources.length} loaded</span>
      </div>

      <ul className="flex flex-wrap gap-2" data-testid="source-list">
        {sources.map((s) => (
          <li key={s.dataset_id}>
            <span
              data-testid="source-chip"
              data-var={s.var_name}
              className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs text-indigo-800"
            >
              <code
                className="rounded bg-white/70 px-1.5 py-0.5 font-mono font-semibold text-indigo-700"
                data-testid="source-var"
              >
                {s.var_name}
              </code>
              <span className="text-indigo-500/80">
                {s.origin && s.origin !== s.filename
                  ? `${s.filename} · ${s.origin}`
                  : s.filename}
              </span>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onRemove(s.dataset_id)}
                aria-label={`Remove ${s.var_name}`}
                data-testid="remove-source"
                className="ml-0.5 rounded-full px-1 text-indigo-400 transition-colors hover:bg-indigo-100 hover:text-indigo-700 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                ×
              </button>
            </span>
          </li>
        ))}
      </ul>

      {sources.length > 1 && (
        <p className="mt-3 text-xs text-slate-500" data-testid="multi-source-hint">
          Ask across files by their names — e.g.{' '}
          <span className="font-medium text-slate-600">
            &ldquo;join {sources[0].var_name} and {sources[1].var_name} on id&rdquo;
          </span>
          .
        </p>
      )}
    </Card>
  )
}
