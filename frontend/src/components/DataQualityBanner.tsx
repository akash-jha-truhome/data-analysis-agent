'use client'

import { useState } from 'react'
import type { DataQuality } from '@/lib/api'

/**
 * Data-quality banner (Phase 2). Renders the profiling the agent noticed while
 * answering (missing values, duplicate rows, outliers) for the CURRENT dataset.
 * Dismissible; expandable for details. Renders NOTHING when there is no quality
 * payload or it flags nothing — so it never reads as a broken box.
 */
export default function DataQualityBanner({ quality }: { quality: DataQuality | null }) {
  const [dismissed, setDismissed] = useState(false)
  const [open, setOpen] = useState(false)

  if (!quality) return null

  const hasMissing = quality.missing && quality.missing.length > 0
  const hasDupes = quality.duplicate_rows > 0
  const hasOutliers = quality.outliers && quality.outliers.length > 0
  const hasAnything = hasMissing || hasDupes || hasOutliers

  // Nothing worth flagging → render nothing (not an empty box).
  if (!hasAnything && !quality.summary) return null
  if (dismissed) return null

  return (
    <div
      className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3"
      data-testid="data-quality-banner"
      role="status"
    >
      <div className="flex items-start gap-3">
        <span aria-hidden className="mt-0.5 text-amber-500">
          ⚠
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-amber-800" data-testid="dq-summary">
            {quality.summary || 'Data-quality issues detected in this dataset.'}
          </p>
          {hasAnything && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="mt-1 text-xs font-medium text-amber-700 underline hover:text-amber-900"
            >
              {open ? 'Hide details' : 'Show details'}
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss data-quality banner"
          className="rounded p-1 text-amber-600 hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500"
        >
          <span aria-hidden>✕</span>
        </button>
      </div>

      {open && hasAnything && (
        <div className="mt-3 space-y-2 border-t border-amber-200 pt-3 text-xs text-amber-800">
          {hasMissing && (
            <div>
              <span className="font-semibold">Missing values:</span>{' '}
              {quality.missing
                .map((m) => `${m.column} (${m.count}, ${m.pct}%)`)
                .join(', ')}
            </div>
          )}
          {hasDupes && (
            <div>
              <span className="font-semibold">Duplicate rows:</span>{' '}
              {quality.duplicate_rows.toLocaleString()}
            </div>
          )}
          {hasOutliers && (
            <div>
              <span className="font-semibold">Outliers:</span>{' '}
              {quality.outliers.map((o) => `${o.column} (${o.count})`).join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
