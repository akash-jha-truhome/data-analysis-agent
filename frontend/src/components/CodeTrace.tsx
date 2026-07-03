'use client'

import type { RunStep } from '@/lib/api'

export default function CodeTrace({
  code,
  steps,
}: {
  code: string | null
  steps: RunStep[]
}) {
  if (!code && (!steps || steps.length === 0)) return null

  return (
    <details className="group rounded-xl border border-slate-200 bg-white shadow-sm" data-testid="code-trace">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-slate-700 select-none">
        <span>Code it ran</span>
        <span className="text-xs font-normal text-slate-400 group-open:hidden">Show</span>
        <span className="hidden text-xs font-normal text-slate-400 group-open:inline">Hide</span>
      </summary>

      <div className="space-y-4 border-t border-slate-100 px-5 py-4">
        {code && (
          <div>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              Generated code
            </p>
            <pre
              data-testid="generated-code"
              className="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs leading-relaxed text-slate-100"
            >
              <code>{code}</code>
            </pre>
          </div>
        )}

        {steps && steps.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              Step trace
            </p>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">Action</th>
                    <th className="px-3 py-2 font-medium">Result</th>
                    <th className="px-3 py-2 font-medium">Duration</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {steps.map((s) => (
                    <tr key={s.step}>
                      <td className="px-3 py-1.5">{s.step}</td>
                      <td className="px-3 py-1.5 font-mono">{s.action}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            s.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                          }`}
                        >
                          {s.ok ? 'ok' : 'error'}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 tabular-nums">{s.duration_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </details>
  )
}
