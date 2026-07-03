'use client'

import { useState } from 'react'
import UploadPanel from '@/components/UploadPanel'
import SourceChips from '@/components/SourceChips'
import QuestionBox from '@/components/QuestionBox'
import SessionThread, { type Turn } from '@/components/SessionThread'
import DataQualityBanner from '@/components/DataQualityBanner'
import HistoryPanel from '@/components/HistoryPanel'
import { Card } from '@/components/ui'
import {
  askQuestion,
  getRun,
  sourcesFromUpload,
  previewFromUpload,
  ApiError,
  type DatasetInfo,
  type DataQuality,
  type Source,
  type UploadResult,
} from '@/lib/api'

let turnCounter = 0
function nextTurnId(): string {
  turnCounter += 1
  return `turn-${turnCounter}`
}

export default function Home() {
  const [sources, setSources] = useState<Source[]>([])
  const [dataset, setDataset] = useState<DatasetInfo | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [asking, setAsking] = useState(false)
  const [reopening, setReopening] = useState(false)
  const [dataQuality, setDataQuality] = useState<DataQuality | null>(null)
  const [historyKey, setHistoryKey] = useState(0)

  function updateTurn(id: string, patch: Partial<Turn>) {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }

  function resetSession() {
    setSessionId(null)
    setTurns([])
    setDataQuality(null)
    setHistoryKey((k) => k + 1)
  }

  function handleUpload(res: UploadResult) {
    const added = sourcesFromUpload(res)
    const preview = previewFromUpload(res)
    setSources((prev) => {
      // First upload starts a fresh session; later uploads add more sources.
      if (prev.length === 0) resetSession()
      const seen = new Set(prev.map((s) => s.dataset_id))
      return [...prev, ...added.filter((s) => !seen.has(s.dataset_id))]
    })
    if (preview) setDataset(preview)
  }

  function removeSource(datasetId: string) {
    setSources((prev) => {
      const next = prev.filter((s) => s.dataset_id !== datasetId)
      if (next.length === 0) {
        setDataset(null)
        resetSession()
      }
      return next
    })
  }

  const primary = sources[0] ?? null
  const datasetIds = sources.map((s) => s.dataset_id)

  async function runAsk(id: string, question: string, clarificationAnswer?: string) {
    if (!primary) return
    setAsking(true)
    try {
      const res = await askQuestion(primary.dataset_id, question, {
        sessionId: sessionId ?? undefined,
        datasetIds,
        clarificationAnswer,
      })
      if (res.session_id) setSessionId(res.session_id)
      if (res.status === 'needs_clarification' && res.clarification) {
        updateTurn(id, { status: 'clarifying', clarification: res.clarification })
      } else {
        updateTurn(id, { status: 'done', result: res, clarification: undefined })
        if (res.data_quality) setDataQuality(res.data_quality)
      }
      setHistoryKey((k) => k + 1)
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : new ApiError('Something went wrong.', 0)
      updateTurn(id, { status: 'error', error: apiErr })
      setHistoryKey((k) => k + 1)
    } finally {
      setAsking(false)
    }
  }

  async function handleAsk(question: string) {
    if (!primary || asking) return
    const id = nextTurnId()
    setTurns((prev) => [...prev, { id, question, status: 'pending' }])
    await runAsk(id, question)
  }

  async function handleClarify(turnId: string, answer: string) {
    if (asking) return
    const turn = turns.find((t) => t.id === turnId)
    if (!turn) return
    updateTurn(turnId, { status: 'pending', clarification: undefined })
    await runAsk(turnId, turn.question, answer)
  }

  async function handleReopen(runId: string) {
    if (reopening) return
    setReopening(true)
    try {
      const run = await getRun(runId)
      const id = nextTurnId()
      setTurns((prev) => [
        ...prev,
        {
          id,
          question: run.question ?? 'Reopened query',
          status: 'done',
          result: run,
          reopened: true,
        },
      ])
      if (run.data_quality) setDataQuality(run.data_quality)
    } catch (err) {
      const id = nextTurnId()
      const apiErr = err instanceof ApiError ? err : new ApiError('Could not reopen that run.', 0)
      setTurns((prev) => [
        ...prev,
        { id, question: 'Reopened query', status: 'error', error: apiErr, reopened: true },
      ])
    } finally {
      setReopening(false)
    }
  }

  const hasThread = turns.length > 0
  const hasSources = sources.length > 0

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          Data Analysis Agent
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload one or more CSV / Excel files, then ask as many questions as you like — across
          files and sheets. Follow-ups remember the conversation, and when a question is ambiguous
          the agent asks one clarifying question first. Each answer comes with the key numbers, an
          interactive chart, and the exact code it ran.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Primary column — the real session journey */}
        <div className="space-y-6 lg:col-span-2">
          {hasSources && (
            <DataQualityBanner key={primary?.dataset_id} quality={dataQuality} />
          )}

          <UploadPanel
            dataset={dataset}
            sessionId={sessionId}
            hasSources={hasSources}
            onUpload={handleUpload}
          />

          <SourceChips sources={sources} onRemove={removeSource} disabled={asking} />

          <div className="flex items-center justify-between gap-3">
            <h2 className="sr-only">Ask</h2>
            {hasThread && (
              <button
                type="button"
                onClick={resetSession}
                data-testid="new-session"
                className="ml-auto rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
              >
                New session
              </button>
            )}
          </div>

          <QuestionBox enabled={hasSources} busy={asking} onAsk={handleAsk} />

          {/* Conversation thread (pending / clarifying / answer / error live inside) */}
          {hasThread && (
            <SessionThread
              turns={turns}
              disabled={asking}
              onPick={handleAsk}
              onClarify={handleClarify}
            />
          )}

          {/* Empty state — before any question */}
          {!hasThread && (
            <Card className="p-8 text-center">
              <p className="text-sm text-slate-500">
                {hasSources
                  ? 'Ask a question about your data to start the conversation.'
                  : 'Upload a CSV or Excel file to get started.'}
              </p>
            </Card>
          )}
        </div>

        {/* Secondary column — run history + running token total */}
        <aside className="space-y-6">
          <HistoryPanel
            sessionId={sessionId}
            refreshKey={historyKey}
            onReopen={handleReopen}
            reopening={reopening}
          />
        </aside>
      </div>
    </main>
  )
}
