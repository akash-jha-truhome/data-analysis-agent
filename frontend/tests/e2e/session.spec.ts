import { test, expect } from '@playwright/test'
import path from 'node:path'

const FIXTURE_CSV = path.join(__dirname, 'fixtures', 'orders.csv')

// Session journey — the REAL Phase 2 "upload once, ask many" flow against the
// live app + real Gemini. Upload a CSV with a date/month column plus missing
// values and duplicate rows, so BOTH conversation memory and data-quality
// profiling are exercised. Assertions are on rendered CONTENT, not just status.
test('upload once → ask, follow-up in thread, suggestions, data quality, history + tokens, reopen', async ({
  page,
}) => {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: 'Data Analysis Agent' })).toBeVisible()

  // 1. Upload the fixture CSV (POST /datasets).
  await page.locator('#csv-input').setInputFiles(FIXTURE_CSV)
  const summary = page.getByTestId('dataset-summary')
  await expect(summary).toBeVisible({ timeout: 30_000 })
  await expect(summary).toContainText('orders.csv')

  // 2. Ask the FIRST question (POST /ask — mints the session).
  await page.getByLabel('Question about your data').fill('total revenue by region')
  await page.getByRole('button', { name: 'Ask' }).click()

  // First answer renders in the thread as real prose.
  const firstAnswer = page.getByTestId('answer-text').first()
  await expect(firstAnswer).toBeVisible({ timeout: 150_000 })
  expect((await firstAnswer.innerText()).trim().length).toBeGreaterThan(10)

  // Auto-suggested follow-up chips appear.
  const chips = page.getByTestId('suggestion-chips').first()
  await expect(chips).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('suggestion-chip').first()).toBeVisible()

  // Data-quality banner appears (fixture has missing values + duplicate rows).
  await expect(page.getByTestId('data-quality-banner')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('dq-summary')).not.toBeEmpty()

  // Session token badge shows a nonzero total after the first answer.
  const badge = page.getByTestId('session-token-badge')
  await expect(badge).toBeVisible()
  await expect(async () => {
    const txt = await badge.innerText()
    const n = parseInt(txt.replace(/[^0-9]/g, ''), 10)
    expect(n).toBeGreaterThan(0)
  }).toPass({ timeout: 20_000 })

  // 3. Ask a CONTEXT-DEPENDENT follow-up in the SAME session.
  await page.getByLabel('Question about your data').fill('now break that down by month')
  await page.getByRole('button', { name: 'Ask' }).click()

  // A second turn's answer renders in the thread (2 answers total).
  await expect
    .poll(async () => page.getByTestId('thread-turn').count(), { timeout: 150_000 })
    .toBeGreaterThanOrEqual(2)
  await expect
    .poll(async () => page.getByTestId('answer-text').count(), { timeout: 150_000 })
    .toBeGreaterThanOrEqual(2)

  // 4. History panel lists >= 2 runs.
  await expect
    .poll(async () => page.getByTestId('history-item').count(), { timeout: 20_000 })
    .toBeGreaterThanOrEqual(2)

  // 5. Reopen a past run → its result re-renders in the thread.
  const turnsBefore = await page.getByTestId('thread-turn').count()
  await page.getByTestId('history-item').last().click()
  await expect
    .poll(async () => page.getByTestId('thread-turn').count(), { timeout: 30_000 })
    .toBeGreaterThan(turnsBefore)
  await expect(page.getByText('Reopened').last()).toBeVisible()
})
