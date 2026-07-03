// Central API client.
//
// IMPORTANT: the frontend is served under `/app` (Next.js static export mounted
// by FastAPI), but the API lives at the ROOT (`/datasets`, `/ask`, `/runs/{id}`).
// Every fetch below therefore uses an ABSOLUTE root path (leading `/`) so it is
// resolved against the origin, NOT against `/app/`. Do not change these to
// relative paths — a relative `datasets` from `/app/` would wrongly hit
// `/app/datasets`.

// ---- Response shapes (mirror spec/api.md exactly) --------------------------

export interface ColumnMeta {
  name: string
  dtype: string
}

export interface DatasetInfo {
  dataset_id: string
  filename: string
  n_rows: number
  n_cols: number
  columns: ColumnMeta[]
  sample_rows: Record<string, unknown>[]
  // Phase 3: the pandas variable name the user can reference in questions
  // (e.g. "orders", "customers", "sales_sheet1").
  var_name?: string
  is_excel?: boolean
}

/** One sheet of an uploaded Excel workbook — each becomes its own source. */
export interface ExcelSheetInfo {
  dataset_id: string
  filename: string
  var_name: string
  n_rows: number
  n_cols: number
  columns: ColumnMeta[]
  sample_rows: Record<string, unknown>[]
}

/** Phase 3 Excel upload response — one dataset per sheet. */
export interface ExcelUpload {
  is_excel: true
  datasets: ExcelSheetInfo[]
}

/**
 * The `POST /datasets` payload is a discriminated union: a single CSV dataset
 * (`is_excel:false`) or an Excel workbook expanded into one source per sheet
 * (`is_excel:true`).
 */
export type UploadResult = (DatasetInfo & { is_excel?: false }) | ExcelUpload

/** A loaded source the user can reference by `var_name` in questions. */
export interface Source {
  dataset_id: string
  var_name: string
  filename: string
  origin?: string
}

export function isExcelUpload(res: UploadResult): res is ExcelUpload {
  return (res as ExcelUpload).is_excel === true
}

/** Flatten an upload response into the list of sources it contributes. */
export function sourcesFromUpload(res: UploadResult): Source[] {
  if (isExcelUpload(res)) {
    return res.datasets.map((d) => ({
      dataset_id: d.dataset_id,
      var_name: d.var_name,
      filename: d.filename,
      origin: d.filename,
    }))
  }
  return [
    {
      dataset_id: res.dataset_id,
      var_name: res.var_name ?? deriveVarName(res.filename),
      filename: res.filename,
    },
  ]
}

/** The DatasetInfo to preview (a CSV directly, or an Excel's first sheet). */
export function previewFromUpload(res: UploadResult): DatasetInfo | null {
  if (isExcelUpload(res)) {
    const first = res.datasets[0]
    if (!first) return null
    return { ...first, is_excel: true }
  }
  return res
}

function deriveVarName(filename: string): string {
  return (
    filename
      .replace(/\.[^.]+$/, '')
      .replace(/[^a-zA-Z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .toLowerCase() || 'data'
  )
}

export interface KeyNumber {
  label: string
  value: number
}

export interface PlotlyFigure {
  data: unknown[]
  layout?: Record<string, unknown>
  // Set by the backend when the result can't be charted (scalar / single column /
  // non-numeric) — `data` is empty and the result should render as a table.
  table_only?: boolean
}

export interface DataTable {
  columns: string[]
  rows: unknown[][]
}

export interface RunStep {
  step: number
  action: string
  ok: boolean
  duration_ms: number
}

export interface TokenUsage {
  prompt: number
  completion: number
  total: number
}

export interface MissingColumn {
  column: string
  count: number
  pct: number
}

export interface OutlierColumn {
  column: string
  count: number
}

export interface DataQuality {
  missing: MissingColumn[]
  duplicate_rows: number
  outliers: OutlierColumn[]
  summary: string
}

export interface AskResult {
  run_id: string
  status: 'completed' | 'failed' | 'needs_clarification'
  answer: string | null
  key_numbers: KeyNumber[]
  chart: PlotlyFigure | null
  table: DataTable | null
  code: string | null
  steps: RunStep[]
  tokens?: TokenUsage | null
  // Phase 2 additions.
  session_id?: string
  suggestions?: string[]
  data_quality?: DataQuality | null
  // Phase 3 clarification gate. When `status:"needs_clarification"` the agent
  // needs an answer before computing: `clarification` holds the question and
  // `answer` is null. Otherwise `needs_clarification:false`, `clarification:null`.
  needs_clarification?: boolean
  clarification?: string | null
  // Present on GET /runs/{id} (the reopened-run payload).
  question?: string
  created_at?: string
}

// ---- Session / history shapes (Phase 2) ------------------------------------

export interface SessionInfo {
  session_id: string
  dataset_id: string
  total_tokens: number
  run_count: number
  created_at: string
}

export interface SessionRunSummary {
  run_id: string
  question: string
  status: 'completed' | 'failed'
  total_tokens: number
  created_at: string
}

export interface SessionRuns {
  session_id: string
  dataset_id: string
  total_tokens: number
  runs: SessionRunSummary[]
}

// Success envelope: { data, error }. Failure: HTTP error with
// { detail: { code, message } }.
interface Envelope<T> {
  data: T | null
  error: unknown
  detail?: { code?: string; message?: string }
}

// ---- Error type ------------------------------------------------------------

export class ApiError extends Error {
  status: number
  code?: string
  /**
   * Best-effort partial run trace, when the backend surfaces the attempted
   * steps/code alongside a failure. Lets the UI still show "what was tried"
   * on an /ask failure without ever showing a fabricated answer/number.
   */
  partial?: AskResult

  constructor(message: string, status: number, code?: string, partial?: AskResult) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.partial = partial
  }
}

async function parseJson(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return null
  }
}

function extractPartial(body: unknown): AskResult | undefined {
  if (body && typeof body === 'object') {
    const data = (body as Envelope<AskResult>).data
    if (data && typeof data === 'object' && 'steps' in data) {
      return data as AskResult
    }
  }
  return undefined
}

// ---- Endpoints -------------------------------------------------------------

/**
 * POST /datasets — multipart upload of a CSV or Excel workbook under field
 * `file`. Phase 3: an optional `session_id` associates the upload with an
 * existing multi-source session, and an Excel workbook expands into one dataset
 * per sheet (`is_excel:true`, `datasets:[…]`).
 */
export async function uploadDataset(
  file: File,
  sessionId?: string,
): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  if (sessionId) form.append('session_id', sessionId)

  let res: Response
  try {
    res = await fetch('/datasets', { method: 'POST', body: form })
  } catch {
    throw new ApiError('Network error — is the server running on :8001?', 0)
  }

  const body = (await parseJson(res)) as Envelope<UploadResult> | null
  if (!res.ok) {
    const message =
      body?.detail?.message ??
      `Couldn't read that file — the upload failed (${res.status}).`
    throw new ApiError(message, res.status, body?.detail?.code)
  }
  if (!body?.data) {
    throw new ApiError('The server returned an unexpected response for the upload.', res.status)
  }
  return body.data
}

/**
 * POST /ask — ask one question about a loaded dataset.
 *
 * Phase 2: pass `sessionId` to continue an existing multi-turn session so the
 * agent remembers prior turns ("now break that down by month"). Omit it on the
 * first question — the backend mints a session and returns its id in
 * `data.session_id`, which the caller threads into subsequent asks.
 */
export interface AskOptions {
  sessionId?: string
  /** ALL currently-loaded source ids (multi-file / Excel sheets). */
  datasetIds?: string[]
  /** The user's reply to a prior clarifying question (clarification gate). */
  clarificationAnswer?: string
}

export async function askQuestion(
  datasetId: string,
  question: string,
  opts: AskOptions = {},
): Promise<AskResult> {
  const { sessionId, datasetIds, clarificationAnswer } = opts
  let res: Response
  try {
    res = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: datasetId,
        question,
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(datasetIds && datasetIds.length > 0 ? { dataset_ids: datasetIds } : {}),
        ...(clarificationAnswer ? { clarification_answer: clarificationAnswer } : {}),
      }),
    })
  } catch {
    throw new ApiError('Network error — is the server running on :8001?', 0)
  }

  const body = (await parseJson(res)) as Envelope<AskResult> | null

  if (!res.ok) {
    const message =
      body?.detail?.message ??
      "Couldn't compute an answer — try rephrasing your question."
    throw new ApiError(message, res.status, body?.detail?.code, extractPartial(body))
  }

  const data = body?.data
  if (!data) {
    throw new ApiError('The server returned an unexpected response for your question.', res.status)
  }

  // A `needs_clarification` 200 is NOT an error — the agent is asking one
  // question before it computes. Return it so the UI can render the exchange.
  if (data.status === 'needs_clarification') {
    return data
  }

  // A 200 can still carry status:"failed" — treat it as an error path so the UI
  // never renders a fabricated answer, but keep the trace so we can show attempts.
  if (data.status === 'failed') {
    throw new ApiError(
      "Couldn't compute an answer — try rephrasing your question.",
      422,
      'agent_failed',
      data,
    )
  }

  return data
}

/** GET /runs/{run_id} — full audit record for a past query, used to REOPEN it. */
export async function getRun(runId: string): Promise<AskResult> {
  const res = await fetch(`/runs/${encodeURIComponent(runId)}`)
  const body = (await parseJson(res)) as Envelope<AskResult> | null
  if (!res.ok || !body?.data) {
    throw new ApiError(body?.detail?.message ?? `Run not found (${res.status}).`, res.status)
  }
  return body.data
}

/** GET /sessions/{session_id} — running session metadata + token total. */
export async function getSession(sessionId: string): Promise<SessionInfo> {
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}`)
  const body = (await parseJson(res)) as Envelope<SessionInfo> | null
  if (!res.ok || !body?.data) {
    throw new ApiError(body?.detail?.message ?? `Session not found (${res.status}).`, res.status)
  }
  return body.data
}

/** GET /sessions/{session_id}/runs — run history (newest-first) + token total. */
export async function getSessionRuns(sessionId: string): Promise<SessionRuns> {
  const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/runs`)
  const body = (await parseJson(res)) as Envelope<SessionRuns> | null
  if (!res.ok || !body?.data) {
    throw new ApiError(body?.detail?.message ?? `Session not found (${res.status}).`, res.status)
  }
  return body.data
}
