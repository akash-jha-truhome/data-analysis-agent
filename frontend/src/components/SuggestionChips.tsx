'use client'

/**
 * Auto-suggested follow-up chips (Phase 2). Rendered after each answer from the
 * `suggestions` array on the /ask response. Clicking a chip submits it as the
 * next question in the SAME session, so the agent keeps its context.
 */
export default function SuggestionChips({
  suggestions,
  disabled,
  onPick,
}: {
  suggestions: string[]
  disabled: boolean
  onPick: (question: string) => void
}) {
  if (!suggestions || suggestions.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="suggestion-chips">
      <span className="text-xs font-medium text-slate-500">Try a follow-up:</span>
      {suggestions.slice(0, 3).map((s, i) => (
        <button
          key={`${s}-${i}`}
          type="button"
          disabled={disabled}
          onClick={() => onPick(s)}
          data-testid="suggestion-chip"
          className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {s}
        </button>
      ))}
    </div>
  )
}
