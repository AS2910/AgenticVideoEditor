import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** Launch item 8 in a real browser (API mocked): a signed-out visitor at the start sees the
 *  landing page (no sideways scroll at 375 px, the demo plays the bundled files, prices
 *  from /pricing) and requests access; an admin sees the waitlist and sends an invite.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const PRICING = {
  trial_credits: 5, credit_usd: 1, topup_months: 12, test_mode: true, languages: false, invite_only: true,
  plans: [
    { plan_id: 'starter', name: 'Starter', credits: 15, blurb: 'For one person trying a few videos a month.', usd: 19, inr: 1599 },
    { plan_id: 'studio', name: 'Studio', credits: 50, blurb: 'For a small team shipping every week.', usd: 59, inr: 4999 },
    { plan_id: 'agency', name: 'Agency', credits: 160, blurb: 'For agencies running campaigns for clients.', usd: 179, inr: 14999 },
  ],
  topups: [{ credits: 10, usd: 12, inr: 1008 }, { credits: 25, usd: 30, inr: 2520 }, { credits: 50, usd: 60, inr: 5040 }],
}

async function signedOut(page: Page, joined: unknown[]) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path.endsWith('/auth/me')) return json({ mode: 'accounts', user: null })
    if (path === '/api/pricing') return json(PRICING)
    if (path === '/api/waitlist') { joined.push(JSON.parse(req.postData() ?? '{}')); return json({ ok: true, message: 'Thanks. You are on the list, and we will email you when there is a place.' }, 201) }
    if (path === '/api/auth/options') return json({ mode: 'accounts', google: false, password: true, email_link: false, invite_only: true, terms_version: 'draft' })
    return json({})
  })
}

for (const width of [375, 1280]) {
  test(`8: the landing page for a signed-out visitor at ${width} px; Request access`, async ({ page }) => {
    const joined: unknown[] = []
    await page.setViewportSize({ width, height: 900 })
    await signedOut(page, joined)
    await page.goto('/')
    await expect(page.getByTestId('landing-page')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Change every ad at once.')
    // No sideways scroll.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    // The demo's two files are served without an account.
    const video = page.getByTestId('demo-video')
    expect((await page.request.get('/sample-ad.mp4')).ok()).toBe(true)
    expect((await page.request.get('/sample-ad-after.mp4')).ok()).toBe(true)
    await page.getByRole('button', { name: 'After' }).click()
    await expect(video).toHaveAttribute('src', '/sample-ad-after.mp4')
    await expect(page.getByTestId('plan-card')).toHaveCount(3)
    await expect(page.getByTestId('plan-card').first()).toContainText('$19 a month')
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/landing-${width}.png`, fullPage: true })
    if (SHOTS) { await page.emulateMedia({ colorScheme: 'dark' }); await page.reload(); await expect(page.getByTestId('plan-card')).toHaveCount(3); await page.screenshot({ path: `${SHOTS}/landing-${width}-dark.png`, fullPage: true }) }

    await page.getByRole('banner').getByRole('button', { name: 'Request access' }).click()
    const form = page.getByRole('form', { name: 'Request access' })
    await form.getByLabel('Email').fill('bo@example.com')
    await form.getByLabel(/What do you make/).fill('cooking shorts')
    await form.getByRole('button', { name: 'Request access' }).click()
    await expect(page.getByTestId('access-done')).toContainText('You are on the list')
    expect(joined).toEqual([{ email: 'bo@example.com', use_case: 'cooking shorts' }])

    // Sign in goes to the door.
    await page.getByRole('link', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/#login$/)
    await expect(page.getByTestId('landing-page')).toHaveCount(0)
  })
}

test('8: an admin sees the waitlist and sends an invite', async ({ page }) => {
  let invited = false
  await page.setViewportSize({ width: 375, height: 900 })
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    const row = { id: 3, email: 'cy@example.com', name: 'Cy', use_case: 'travel vlogs', created_at: '2026-10-22T10:00:00+00:00',
      invited_at: invited ? '2026-10-23T08:00:00+00:00' : null, invited_by: invited ? 'acct:admin' : null, status: invited ? 'invited' : 'waiting' }
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json({ flags: ['golive.g7'] })
    if (path.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true })
    if (path === '/api/me/admin') return json({ admin: true })
    if (path === '/api/admin/waitlist') return json({ rows: [row], invite_only: true })
    if (path === '/api/admin/analytics') return json({ funnel: [], take_acceptance: { voiced: 0, added: 0, rate: null },
      cost_per_exported_minute: { cost_usd: 0, minutes: 0, per_minute: null }, vendor_quality: [], counts: [] })
    if (path === '/api/admin/waitlist/3/invite' && req.method() === 'POST') { invited = true; return json({ row: { ...row, status: 'invited', invited_at: '2026-10-23T08:00:00+00:00', invited_by: 'acct:admin' } }) }
    if (path === '/api/me/notifications/count') return json({ unread: 0 })
    return json({})
  })
  await page.goto('/#admin')
  const card = page.getByTestId('admin-waitlist')
  await expect(card.getByTestId('waitlist-row')).toHaveCount(1)
  await expect(card.getByTestId('waitlist-row')).toContainText('Waiting')
  await card.getByRole('button', { name: 'Send invite to cy@example.com' }).click()
  await expect(card.getByTestId('waitlist-row')).toContainText('Invited')
  await expect(card.getByTestId('waitlist-row')).toContainText('by acct:admin')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/admin-waitlist-375.png`, fullPage: true })
})
