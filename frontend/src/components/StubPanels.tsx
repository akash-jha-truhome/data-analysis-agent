'use client'

import { Card, ComingSoon } from '@/components/ui'

/**
 * Remaining Phase 3 stubs — clearly-labelled, non-functional, visually distinct
 * so none reads as a bug. Wired in Phase 3 (multi-file + Excel sheets +
 * clarification gate). The "Add another file / sheet" affordance lives in
 * UploadPanel; this panel covers the other two deferred capabilities.
 */
export function Phase3Stubs() {
  return (
    <Card className="p-5 opacity-80" aria-hidden>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-700">Coming later</h2>
        <ComingSoon label="Phase 3" />
      </div>
      <ul className="space-y-2">
        <li className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2.5">
          <p className="text-xs font-medium text-slate-500">Excel multi-sheet analysis</p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            Load and reference several sheets from one workbook.
          </p>
        </li>
        <li className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-2.5">
          <p className="text-xs font-medium text-slate-500">Clarifying questions</p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            When a question is ambiguous, the agent will ask one question first.
          </p>
        </li>
      </ul>
    </Card>
  )
}
