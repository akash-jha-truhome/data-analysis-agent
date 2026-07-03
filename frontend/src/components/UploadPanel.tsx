'use client'

import { useRef, useState } from 'react'
import { uploadDataset, ApiError, type DatasetInfo } from '@/lib/api'
import { Card, ComingSoon, Spinner } from '@/components/ui'

export default function UploadPanel({
  dataset,
  onLoaded,
}: {
  dataset: DatasetInfo | null
  onLoaded: (info: DatasetInfo) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File | undefined | null) {
    if (!file) return
    setError(null)
    if (!/\.csv$/i.test(file.name)) {
      setError(`"${file.name}" isn't a CSV — pick a .csv file to continue.`)
      return
    }
    setBusy(true)
    try {
      const info = await uploadDataset(file)
      onLoaded(info)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Upload failed — please try again.'
      setError(message)
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-800">1 · Upload a dataset</h2>
        <span
          className="inline-flex items-center gap-2 opacity-70"
          title="Multiple files / Excel sheets arrive in a later phase"
        >
          <span className="text-xs text-slate-400">Add another file / sheet</span>
          <ComingSoon />
        </span>
      </div>

      <label
        htmlFor="csv-input"
        onDragOver={(e) => {
          e.preventDefault()
          setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragActive(false)
          handleFile(e.dataTransfer.files?.[0])
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${
          dragActive
            ? 'border-indigo-400 bg-indigo-50'
            : 'border-slate-300 bg-slate-50 hover:border-indigo-300 hover:bg-slate-100'
        } ${busy ? 'pointer-events-none opacity-60' : ''}`}
      >
        <input
          id="csv-input"
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => handleFile(e.target.files?.[0])}
          disabled={busy}
        />
        {busy ? (
          <Spinner label="Reading your CSV…" />
        ) : (
          <>
            <span className="text-sm font-medium text-slate-700">
              Drag a CSV here, or <span className="text-indigo-600 underline">browse</span>
            </span>
            <span className="mt-1 text-xs text-slate-400">
              Upload a CSV to get started — it stays loaded for every question you ask.
            </span>
          </>
        )}
      </label>

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </p>
      )}

      {dataset && !busy && (
        <div className="mt-4" data-testid="dataset-summary">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-sm font-semibold text-slate-800">{dataset.filename}</span>
            <span className="text-xs text-slate-500">
              {dataset.n_rows.toLocaleString()} rows · {dataset.n_cols} columns
            </span>
          </div>
          <SamplePreview dataset={dataset} />
        </div>
      )}
    </Card>
  )
}

function SamplePreview({ dataset }: { dataset: DatasetInfo }) {
  const cols = dataset.columns.map((c) => c.name)
  const rows = dataset.sample_rows.slice(0, 5)
  if (cols.length === 0 || rows.length === 0) {
    return <p className="mt-2 text-xs text-slate-400">No sample rows to preview.</p>
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-left text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            {dataset.columns.map((c) => (
              <th key={c.name} className="whitespace-nowrap px-3 py-2 font-medium">
                {c.name}
                <span className="ml-1 font-normal text-slate-400">{c.dtype}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row, i) => (
            <tr key={i} className="text-slate-700">
              {cols.map((c) => (
                <td key={c} className="whitespace-nowrap px-3 py-1.5">
                  {formatCell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? v.toString() : v.toLocaleString()
  return String(v)
}
