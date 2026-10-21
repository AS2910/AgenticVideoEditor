import { defineConfig } from '@playwright/test'

/** Layout tests in a real browser (2026-10-20): the editor shell at desktop sizes.
 *  The API is mocked in each test (no backend); Chrome is the one installed on the machine. */
// PW_PORT lets two checkouts run the layout tests at once (each its own Vite).
const port = Number(process.env.PW_PORT || 5181)

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  // Launch item 11: a loaded machine can take more than 5 s to settle a focus or a scroll.
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${port}`, channel: 'chrome', headless: true },
  webServer: { command: `npx vite --port ${port} --strictPort`, url: `http://localhost:${port}`, reuseExistingServer: !process.env.PW_PORT, timeout: 60_000 },
})
