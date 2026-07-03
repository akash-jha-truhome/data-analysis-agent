import { defineConfig, devices } from '@playwright/test'

// The golden-path E2E runs against the LIVE app: FastAPI serves the built static
// export at http://localhost:8001/app/ and exposes the real API at the root. The
// orchestrator/qa starts that server (with real keys from .env) before running
// `pnpm exec playwright test` — this config does NOT start it.
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  // Real Gemini round-trips are slow; give the journey generous headroom.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: 'http://localhost:8001/app/',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
