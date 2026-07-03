'use client'

import ResultView from '@/components/ResultView'
import CodeTrace from '@/components/CodeTrace'
import StepIndicator from '@/components/StepIndicator'
import SuggestionChips from '@/components/SuggestionChips'
import ClarificationBox from '@/components/ClarificationBox'
import { Card } from '@/components/ui'
import type { ApiError, AskResult } from '@/lib/api'

export interface Turn {
  id: string
  question: string
  status: 'pending' | 'clarifying' | 'done' | 'error'
  result?: AskResult
  error?: ApiError
  reopened?: boolean
  // Phase 3 clarification gate: the agent's question while awaiting a reply.
  clarification?: string
}

/**
 * Conversation thread (Phase 2). Renders each Q&A turn in order so follow-ups
 * like "now break that down by month" read as a natural thread. The dataset
 * stays loaded across turns; each turn's suggestions submit the next question
 * in the SAME session.
 */
export default function SessionThread({
  turns,
  disabled,
  onPick,
  onClarify,
}: {
  turns: Turn[]
  disabled: boolean
  onPick: (question: string) => void
  onClarify: (turnId: string, answer: string) => void
}) {
  return (
    <div className="space-y-6" data-testid="session-thread">
      {turns.map((turn) => (
        <div key={turn.id} className="space-y-3" data-testid="thread-turn">
          {/* The question that opened this turn */}
          <div className="flex items-start gap-2">
            <span className="mt-0.5 rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
              {turn.reopened ? 'Reopened' : 'You'}
            </span>
            <p className="text-sm font-medium text-slate-800" data-testid="thread-question">
              {turn.question}
            </p>
          </div>

          {/* In-flight */}
          {turn.status === 'pending' && <StepIndicator />}

          {/* Clarification gate — the agent asks one question before computing */}
          {turn.status === 'clarifying' && turn.clarification && (
            <ClarificationBox
              question={turn.clarification}
              busy={disabled}
              onAnswer={(answer) => onClarify(turn.id, answer)}
            />
          )}

          {/* Failure — human message, never a fabricated number */}
          {turn.status === 'error' && turn.error && (
            <div className="space-y-4">
              <Card className="border-red-200 bg-red-50 p-6">
                <h3
                  className="text-sm font-semibold text-red-800"
                  role="alert"
                  data-testid="ask-error"
                >
                  Couldn&apos;t compute an answer
                </h3>
                <p className="mt-1 text-sm text-red-700">{turn.error.message}</p>
                <p className="mt-2 text-xs text-red-600/80">
                  Try rephrasing your question, or make it more specific about the columns in your
                  data.
                </p>
              </Card>
              {turn.error.partial && (
                <CodeTrace code={turn.error.partial.code} steps={turn.error.partial.steps} />
              )}
            </div>
          )}

          {/* Answer */}
          {turn.status === 'done' && turn.result && (
            <>
              <ResultView result={turn.result} />
              {turn.result.suggestions && turn.result.suggestions.length > 0 && (
                <SuggestionChips
                  suggestions={turn.result.suggestions}
                  disabled={disabled}
                  onPick={onPick}
                />
              )}
            </>
          )}
        </div>
      ))}
    </div>
  )
}
