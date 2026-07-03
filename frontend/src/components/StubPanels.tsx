'use client'

import { Card, ComingSoon } from '@/components/ui'

/** Data-quality flags banner slot — Phase 2. Clearly non-functional. */
export function DataQualityBanner() {
  return (
    <div
      className="flex items-center gap-2 rounded-xl border border-dashed border-amber-300 bg-amber-50/60 px-4 py-2.5 opacity-80"
      aria-hidden
    >
      <span className="text-sm text-amber-700">Data-quality flags</span>
      <span className="text-xs text-amber-600/80">
        (missing values, type mismatches, outliers)
      </span>
      <span className="ml-auto">
        <ComingSoon />
      </span>
    </div>
  )
}

/** Session history side panel + running token-total badge — Phase 2. */
export function SessionHistoryPanel() {
  return (
    <Card className="p-5 opacity-80" aria-hidden>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-700">Session history</h2>
        <ComingSoon />
      </div>

      <div className="mb-4 flex items-center justify-between rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2">
        <span className="text-xs text-slate-500">Session tokens</span>
        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-500">
          — total
        </span>
      </div>

      <ul className="space-y-2">
        {[1, 2, 3].map((i) => (
          <li
            key={i}
            className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-400"
          >
            <div className="h-2.5 w-2/3 rounded bg-slate-200" />
            <div className="mt-1.5 h-2 w-1/3 rounded bg-slate-100" />
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-400">
        Past questions and their answers will live here once sessions land.
      </p>
    </Card>
  )
}
