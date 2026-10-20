import { defineConfig } from '@playwright/test'

/** Layout tests in a real browser (2026-10-20): the editor shell at desktop sizes.
 *  The API is mocked in each test (no backend); Chrome is the one installed on the machine. */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5181', channel: 'chrome', headless: true },
  webServer: { command: 'npx vite --port 5181 --strictPort', url: 'http://localhost:5181', reuseExistingServer: true, timeout: 60_000 },
})
