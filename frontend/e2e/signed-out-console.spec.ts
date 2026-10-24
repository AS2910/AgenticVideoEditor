import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** Run 4 item 4c in a real browser (API mocked as the server answers someone signed
 *  out): the landing page and the sign-in page make no call that needs a session, so
 *  the console logs no 401. Before, the flags, onboarding and media token were asked
 *  for before the app knew nobody was signed in. */

const PUBLIC = ['/api/auth/me', '/api/auth/options', '/api/pricing', '/api/auth/email', '/api/waitlist']

async function signedOut(page: Page, asked: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const path = new URL(route.request().url()).pathname
    asked.push(path)
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path === '/api/auth/me') return json({ mode: 'accounts', user: null })
    if (path === '/api/auth/options') return json({ mode: 'accounts', google: false, password: true, email_link: false, invite_only: false, terms_version: 'draft' })
    if (path === '/api/pricing') return json({ trial_credits: 5, credit_usd: 1, topup_months: 12, test_mode: true, languages: false, invite_only: false, plans: [], topups: [] })
    if (PUBLIC.includes(path)) return json({})
    return json({ detail: 'Sign in to continue.' }, 401)        // what the server says to anything else
  })
}

for (const [name, at, testId] of [['landing', '/', 'landing-page'], ['sign-in', '/#login', null]] as const) {
  test(`4c: the ${name} page logs no 401 for someone signed out`, async ({ page }) => {
    const asked: string[] = []
    const logged: string[] = []
    page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') logged.push(m.text()) })
    await signedOut(page, asked)
    await page.goto(at)
    if (testId) await expect(page.getByTestId(testId)).toBeVisible()
    else await expect(page.getByRole('button', { name: /sign in/i }).first()).toBeVisible()
    // Give any late call (a timer, the tour, the bell) a moment to fire.
    await page.waitForTimeout(1500)
    expect(asked.filter((p) => !PUBLIC.includes(p))).toEqual([])
    expect(logged.filter((t) => t.includes('401'))).toEqual([])
  })
}
