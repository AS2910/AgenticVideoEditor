import { defineConfig } from '@playwright/test'

/** The launch rehearsal journeys (2026-10-23): real browser, real stack, nothing mocked in the
 *  browser. They drive the docker-compose rehearsal stack (`scripts/rehearsal.sh up`, port 8080
 *  or REHEARSAL_URL), whose vendors are stand-ins (AVE_MOCK_VENDORS=1). See docs/rehearsal/README.md. */
export default defineConfig({
  testDir: './e2e/rehearsal',
  // A journey makes accounts, takes turns and waits for renders on a loaded machine.
  timeout: 8 * 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.REHEARSAL_URL ?? 'http://localhost:8080',
    channel: 'chrome',
    headless: true,
    viewport: { width: 1280, height: 800 },
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    screenshot: 'only-on-failure',
  },
})
