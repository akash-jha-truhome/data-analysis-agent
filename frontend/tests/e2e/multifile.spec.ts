import { test, expect } from '@playwright/test'
import path from 'node:path'

const ORDERS = path.join(__dirname, 'fixtures', 'orders_join.csv')
const CUSTOMERS = path.join(__dirname, 'fixtures', 'customers.csv')

// Phase 3 — multi-file + clarification gate, against the live app + real Gemini.
// Upload TWO related CSVs into one session, ask a cross-file question, and drive
// the clarifying-question exchange. Assertions are on rendered CONTENT.
test('multi-file join + clarification exchange', async ({ page }) => {
  await page.goto('/app/')
  await expect(page.getByRole('heading', { name: 'Data Analysis Agent' })).toBeVisible()

  // 1. Upload the first CSV (orders) — starts the session.
  await page.locator('#csv-input').setInputFiles(ORDERS)
  await expect(page.getByTestId('dataset-summary')).toBeVisible({ timeout: 30_000 })

  // 2. Upload the second CSV (customers) into the SAME session.
  await page.locator('#csv-input').setInputFiles(CUSTOMERS)

  // Both sources render as chips, each labelled with its var_name.
  await expect
    .poll(async () => page.getByTestId('source-chip').count(), { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2)
  const chips = page.getByTestId('source-chip')
  await expect(chips.filter({ hasText: 'orders_join.csv' })).toBeVisible()
  await expect(chips.filter({ hasText: 'customers.csv' })).toBeVisible()
  // Each chip exposes a non-empty var_name the user can reference.
  const vars = page.getByTestId('source-var')
  await expect(vars.first()).not.toBeEmpty()
  await expect(vars.nth(1)).not.toBeEmpty()

  // 3. Ask a CROSS-FILE question that must join both files to answer.
  await page
    .getByLabel('Question about your data')
    .fill('for each customer name, total order amount, joining the two files on customer_id')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()

  // A computed answer renders in the thread (real prose + a table/chart).
  const answer = page.getByTestId('answer-text').first()
  await expect(answer).toBeVisible({ timeout: 180_000 })
  expect((await answer.innerText()).trim().length).toBeGreaterThan(10)
  await expect(
    page.getByTestId('chart').first().or(page.getByTestId('data-table').first()),
  ).toBeVisible({ timeout: 20_000 })

  // 4. Ambiguous question → the conservative clarification gate MAY fire with an
  // inline input, or (per spec) the agent may best-guess-and-answer directly.
  // Both are valid; exercise the clarification round-trip when it fires and
  // otherwise assert a direct answer — never flaky on the LLM's choice.
  const answersBefore = await page.getByTestId('answer-text').count()
  await page.getByLabel('Question about your data').fill('which one is the best?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()

  const clarify = page.getByTestId('clarification-box')
  const clarified = await clarify
    .waitFor({ state: 'visible', timeout: 180_000 })
    .then(() => true)
    .catch(() => false)

  if (clarified) {
    // 5a. Clarification fired — answer it; a final answer renders in the SAME turn.
    await expect(page.getByTestId('clarification-question')).not.toBeEmpty()
    await page.getByTestId('clarification-input').fill('by total order amount per customer')
    await page.getByTestId('clarification-submit').click()
    await expect(clarify).toBeHidden({ timeout: 180_000 })
  }

  // 5b. Either path ends in a new answer rendered in the thread.
  await expect
    .poll(async () => page.getByTestId('answer-text').count(), { timeout: 180_000 })
    .toBeGreaterThan(answersBefore)
})
