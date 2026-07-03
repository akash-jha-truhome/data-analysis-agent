'use client'

import { useEffect, useState } from 'react'
import { getSessionRuns, ApiError, type SessionRunSummary } from '@/lib/api'
import { Card, Spinner } from '@/components/ui'
import TokenBadge from '@/components/TokenBadge'

/**
 * Run-history panel (Phase 2). Lists this session's past queries newest-first
 * (from GET /sessions/{id}/runs), shows the running session token total, and
 * REOPENS a past run (GET /runs/{id}) when clicked.
 */
export default function HistoryPanel({
  sessionId,
  refreshKey,
  onReopen,
  reopening,
}: {
  sessionId: string | null
  refreshKey: number
  onReopen: (runId: string) => void
  reopening: boolean
}) {
  const [runs, setRuns] = useState<SessionRunSummary[]>([])
  const [totalTokens, setTotalTokens] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) {
      setRuns([])
      setTotalTokens(null)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    getSessionRuns(sessionId)
      .then((data) => {
        if (cancelled) return
        setRuns(data.runs)
        setTotalTokens(data.total_tokens)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Could not load session history.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [sessionId, refreshKey])

  return (
    <Card className="p-5" data-testid="history-panel">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-700">Session history</h2>
        <TokenBadge total={totalTokens} />
      </div>

      {/* No session yet */}
      {!sessionId && (
        <p className="text-xs text-slate-400">
          Ask your first question and your session history will appear here.
        </p>
      )}

      {/* Loading */}
      {sessionId && loading && runs.length === 0 && (
        <div className="py-2">
          <Spinner label="Loading history…" />
        </div>
      )}

      {/* Error */}
      {sessionId && error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {/* Empty (session exists but no runs yet) */}
      {sessionId && !loading && !error && runs.length === 0 && (
        <p className="text-xs text-slate-400">No questions asked yet in this session.</p>
      )}

      {/* Populated */}
      {runs.length > 0 && (
        <ul className="space-y-2" data-testid="history-list">
          {runs.map((r) => (
            <li key={r.run_id}>
              <button
                type="button"
                disabled={reopening}
                onClick={() => onReopen(r.run_id)}
                data-testid="history-item"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-left transition-colors hover:border-indigo-300 hover:bg-indigo-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="line-clamp-2 text-xs font-medium text-slate-700">
                    {r.question}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                      r.status === 'completed'
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-red-50 text-red-700'
                    }`}
                  >
                    {r.status}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                  <span className="tabular-nums">{r.total_tokens.toLocaleString()} tok</span>
                  <span aria-hidden>·</span>
                  <span>{formatTime(r.created_at)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
