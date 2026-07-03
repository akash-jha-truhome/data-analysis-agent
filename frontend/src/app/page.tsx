'use client'

import { useState } from 'react'
import UploadPanel from '@/components/UploadPanel'
import QuestionBox from '@/components/QuestionBox'
import StepIndicator from '@/components/StepIndicator'
import ResultView from '@/components/ResultView'
import CodeTrace from '@/components/CodeTrace'
import { Card } from '@/components/ui'
import { DataQualityBanner, SessionHistoryPanel } from '@/components/StubPanels'
import { askQuestion, ApiError, type DatasetInfo, type AskResult } from '@/lib/api'

export default function Home() {
  const [dataset, setDataset] = useState<DatasetInfo | null>(null)
  const [asking, setAsking] = useState(false)
  const [result, setResult] = useState<AskResult | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  async function handleAsk(question: string) {
    setAsking(true)
    setError(null)
    setResult(null)
    try {
      const res = await askQuestion(dataset!.dataset_id, question)
      setResult(res)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Something went wrong.', 0))
    } finally {
      setAsking(false)
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          Data Analysis Agent
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a CSV, ask a question in plain English, and get a computed answer, an interactive
          chart, and the exact code it ran.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Primary column — the real Phase 1 journey */}
        <div className="space-y-6 lg:col-span-2">
          <DataQualityBanner />

          <UploadPanel dataset={dataset} onLoaded={setDataset} />

          <QuestionBox enabled={!!dataset} busy={asking} onAsk={handleAsk} />

          {/* Loading */}
          {asking && <StepIndicator />}

          {/* Error — human message, never a fabricated number */}
          {!asking && error && (
            <div className="space-y-4">
              <Card className="border-red-200 bg-red-50 p-6">
                <h2 className="text-sm font-semibold text-red-800" role="alert" data-testid="ask-error">
                  Couldn&apos;t compute an answer
                </h2>
                <p className="mt-1 text-sm text-red-700">{error.message}</p>
                <p className="mt-2 text-xs text-red-600/80">
                  Try rephrasing your question, or make it more specific about the columns in your
                  data.
                </p>
              </Card>
              {/* Still show what was attempted, when the backend surfaces a trace */}
              {error.partial && (
                <CodeTrace code={error.partial.code} steps={error.partial.steps} />
              )}
            </div>
          )}

          {/* Ideal / populated */}
          {!asking && !error && result && <ResultView result={result} />}

          {/* Empty states */}
          {!asking && !error && !result && (
            <Card className="p-8 text-center">
              <p className="text-sm text-slate-500">
                {dataset
                  ? 'Ask a question about your data to see the answer, chart, and code here.'
                  : 'Upload a CSV to get started.'}
              </p>
            </Card>
          )}
        </div>

        {/* Secondary column — labelled Phase 2 stubs */}
        <aside className="space-y-6">
          <SessionHistoryPanel />
        </aside>
      </div>
    </main>
  )
}
