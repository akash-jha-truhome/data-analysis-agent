'use client'

import { useState } from 'react'

/**
 * Inline clarification exchange (Phase 3 clarification gate). When an `/ask`
 * response is `status:"needs_clarification"` the agent asks ONE question before
 * computing. This renders that question inside the thread turn with a text input
 * so the user can reply; the answer is re-submitted with the SAME question plus
 * `clarification_answer`. It reads as a natural back-and-forth, not an error.
 */
export default function ClarificationBox({
  question,
  busy,
  onAnswer,
}: {
  question: string
  busy: boolean
  onAnswer: (answer: string) => void
}) {
  const [answer, setAnswer] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const a = answer.trim()
    if (!a || busy) return
    onAnswer(a)
  }

  return (
    <div
      data-testid="clarification-box"
      className="rounded-xl border border-amber-200 bg-amber-50 p-4"
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 rounded-full bg-amber-200 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800">
          Agent
        </span>
        <p
          className="text-sm font-medium text-amber-900"
          data-testid="clarification-question"
        >
          {question}
        </p>
      </div>

      <form onSubmit={submit} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          disabled={busy}
          placeholder="Type your answer…"
          aria-label="Answer the clarifying question"
          data-testid="clarification-input"
          className="flex-1 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
        />
        <button
          type="submit"
          disabled={busy || !answer.trim()}
          data-testid="clarification-submit"
          className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? 'Working…' : 'Reply'}
        </button>
      </form>
    </div>
  )
}
