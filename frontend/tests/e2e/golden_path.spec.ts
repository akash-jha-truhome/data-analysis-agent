import { test, expect } from '@playwright/test'
import path from 'node:path'

const FIXTURE_CSV = path.join(__dirname, 'fixtures', 'sales.csv')

// Golden path — the REAL Phase 1 journey against the live app + real Gemini:
// open the page → upload a CSV → ask a question → read the computed answer,
// the interactive chart, the data-table behind it, and the code it ran.
test('upload → ask → answer + chart + table + code', async ({ page }) => {
  // 1. Page loads and is styled.
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: 'Data Analysis Agent' })).toBeVisible()
  // Styling actually compiled (Tailwind utility applied to <body>).
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  expect(bg).not.toBe('rgba(0, 0, 0, 0)')

  // Empty-state guidance is present before upload.
  await expect(page.getByText(/Upload one or more CSV \/ Excel files/i)).toBeVisible()

  // 2. Upload the fixture CSV (POST /datasets).
  await page.locator('#csv-input').setInputFiles(FIXTURE_CSV)
  const summary = page.getByTestId('dataset-summary')
  await expect(summary).toBeVisible({ timeout: 30_000 })
  await expect(summary).toContainText('sales.csv')
  await expect(summary).toContainText('columns')

  // 3. Ask a question (POST /ask → real agent run).
  await page.getByLabel('Question about your data').fill('total revenue by region')
  await page.getByRole('button', { name: 'Ask' }).click()

  // 4. The answer renders as real prose content.
  const answer = page.getByTestId('answer-text')
  await expect(answer).toBeVisible({ timeout: 150_000 })
  const answerText = (await answer.innerText()).trim()
  expect(answerText.length).toBeGreaterThan(10)

  // 5. An interactive chart (Plotly) is present.
  const chart = page.getByTestId('chart')
  await expect(chart).toBeVisible()
  await expect(chart.locator('.js-plotly-plot').first()).toBeVisible({ timeout: 20_000 })

  // 6. "Show data table" toggle reveals the table behind the chart.
  await page.getByTestId('toggle-table').click()
  const table = page.getByTestId('data-table')
  await expect(table).toBeVisible()
  await expect(table.locator('tbody tr').first()).toBeVisible()

  // 7. "Code it ran" block contains real code.
  const trace = page.getByTestId('code-trace')
  await expect(trace).toBeVisible()
  await trace.locator('summary').click()
  const code = page.getByTestId('generated-code')
  await expect(code).toBeVisible()
  expect((await code.innerText()).trim().length).toBeGreaterThan(0)
})
