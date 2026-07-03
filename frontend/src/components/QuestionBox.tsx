'use client'

import { useState } from 'react'
import { Card } from '@/components/ui'

export default function QuestionBox({
  enabled,
  busy,
  onAsk,
}: {
  enabled: boolean
  busy: boolean
  onAsk: (question: string) => void
}) {
  const [question, setQuestion] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const q = question.trim()
    if (!q || !enabled || busy) return
    onAsk(q)
  }

  return (
    <Card className="p-5">
      <h2 className="mb-3 text-sm font-semibold text-slate-800">2 · Ask a question</h2>

      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={!enabled || busy}
          placeholder={
            enabled ? 'e.g. total revenue by region' : 'Upload a CSV first to ask a question'
          }
          aria-label="Question about your data"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
        />
        <button
          type="submit"
          disabled={!enabled || busy || !question.trim()}
          className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? 'Working…' : 'Ask'}
        </button>
      </form>
    </Card>
  )
}
