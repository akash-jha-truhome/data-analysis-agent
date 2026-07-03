'use client'

import { useEffect, useState } from 'react'
import { Card, Spinner } from '@/components/ui'

// Phase 1: /ask is a single round-trip that returns the full trace, so we make
// progress feel live by cycling the real stages the agent moves through while
// the request is in flight. This reflects the actual pipeline (write → run →
// chart), it is not a fake "busy" animation over an instant operation.
const STAGES = ['Writing code…', 'Running…', 'Charting…']

export default function StepIndicator() {
  const [i, setI] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setI((prev) => Math.min(prev + 1, STAGES.length - 1)), 1400)
    return () => clearInterval(id)
  }, [])

  return (
    <Card className="p-5" data-testid="progress">
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="text-sm font-medium text-slate-700">{STAGES[i]}</span>
      </div>
      <ol className="mt-3 flex flex-wrap gap-2">
        {STAGES.map((label, idx) => (
          <li
            key={label}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              idx < i
                ? 'bg-emerald-50 text-emerald-700'
                : idx === i
                  ? 'bg-indigo-50 text-indigo-700'
                  : 'bg-slate-100 text-slate-400'
            }`}
          >
            {label.replace('…', '')}
          </li>
        ))}
      </ol>
    </Card>
  )
}
