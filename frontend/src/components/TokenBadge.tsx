'use client'

/** Running session token-total badge (Phase 2). */
export default function TokenBadge({ total }: { total: number | null }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-semibold text-indigo-700"
      data-testid="session-token-badge"
      title="Total tokens used across this session"
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
      {total === null ? '—' : total.toLocaleString()} tokens
    </span>
  )
}
