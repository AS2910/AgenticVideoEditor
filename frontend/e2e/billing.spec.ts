import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** G3 in a real browser (API mocked): the Billing page shows the free trial and test mode,
 *  a top-up and a plan go through the fake provider and make invoices, India's details switch
 *  the provider to Razorpay and the prices to rupees. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const FLAGS = { flags: ['golive.g3', 'golive.g4'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true }
const STATES = [{ code: '29', name: 'Karnataka' }, { code: '27', name: 'Maharashtra' }]
const plans = (inr: boolean) => [['starter', 'Starter', 15, 19, 1599, 'For one person trying a few videos a month.'], ['studio', 'Studio', 50, 59, 4999, 'For a small team shipping every week.'],
  ['agency', 'Agency', 160, 179, 14999, 'For agencies running campaigns for clients.']].map(([plan_id, name, credits, usd, rupees, blurb]) =>
  ({ plan_id, name, credits, usd, inr: rupees, blurb, price: inr ? rupees : usd, currency: inr ? 'INR' : 'USD' }))

async function serve(page: Page, posts: string[]) {
  let country: string | null = null
  let plan: string | null = null
  let granted = 5
  const invoices: unknown[] = []
  const view = () => {
    const inr = country === 'IN'
    const ps = plans(inr)
    return {
      account: { owner: 'local', plan, country, legal_name: '', gstin: '', state_code: inr ? '29' : null, created_at: '' },
      credits: { granted, used: 1.2, left: granted - 1.2, share: 1.2 / granted, minutes: null, grants: [] },
      plan: ps.find((p) => p.plan_id === plan) ?? null, plans: ps,
      topups: [10, 25, 50].map((c) => ({ credits: c, price: inr ? c * 1.2 * 84 : c * 1.2, currency: inr ? 'INR' : 'USD' })),
      provider: inr ? { name: 'razorpay', label: 'Razorpay (test mode)', test_mode: true } : { name: 'stripe', label: 'Stripe (test mode)', test_mode: true },
      trial_credits: 5, invoices: [...invoices].reverse(), states: STATES,
    }
  }
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET' && path !== '/api/analytics/events') posts.push(`${method} ${path} ${req.postData() ?? ''}`)
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/billing') return json(view())
    if (path === '/api/billing/topup') {
      const c = JSON.parse(req.postData() ?? '{}').credits
      granted += c
      const inv = { id: invoices.length + 1, number: `VLT-202610-0000${invoices.length + 1}`, provider: 'stripe', checkout_id: 'cs_test_00001', kind: 'topup', description: `Top-up: ${c} credits`, currency: 'USD', subtotal: c * 1.2, cgst: 0, sgst: 0, igst: 0, total: c * 1.2, tax_kind: 'export', issued_at: '2026-10-21T00:00:00Z', test_mode: true }
      invoices.push(inv)
      return json({ ...view(), invoice: inv })
    }
    if (path === '/api/billing/plan') {
      plan = JSON.parse(req.postData() ?? '{}').plan
      granted += 50
      const inv = { id: invoices.length + 1, number: `VLT-202610-0000${invoices.length + 1}`, provider: country === 'IN' ? 'razorpay' : 'stripe', checkout_id: 'order_test_00002', kind: 'plan', description: 'Studio plan, 2026-10: 50 credits a month', currency: country === 'IN' ? 'INR' : 'USD', subtotal: 4999, cgst: 449.91, sgst: 449.91, igst: 0, total: 5898.82, tax_kind: 'intra', issued_at: '2026-10-21T00:00:00Z', test_mode: true }
      invoices.push(inv)
      return json({ ...view(), invoice: inv })
    }
    if (path === '/api/billing/details') { country = JSON.parse(req.postData() ?? '{}').country; return json(view()) }
    if (path.includes('/spend')) return json({ month: { spent_usd: 1.2, ceiling_usd: 100, label: 'October' }, binding: null })
    if (path === '/api/me/notifications/count') return json({ unread: 0 })
    return json({})
  })
}

test('G3: the trial, a top-up, India details and a plan, all in test mode', async ({ page }) => {
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, posts)
  await page.goto('/#billing')
  const card = page.getByTestId('credits-card')
  await expect(card).toContainText('Free trial')
  await expect(card).toContainText('Test mode')
  await expect(page.getByTestId('credits-left')).toHaveText('3.80 credits')
  await page.getByRole('button', { name: '10 credits · $12.00' }).click()
  await expect(page.getByTestId('billing-status')).toHaveText('10 credits added. Paid in test mode: no money moved.')
  await expect(page.getByTestId('invoice-row')).toHaveCount(1)
  await page.getByLabel('Country').selectOption('IN')
  await expect(page.getByLabel('GSTIN (optional)')).toBeVisible()
  await page.getByRole('button', { name: 'Save details' }).click()
  await expect(page.getByTestId('billing-status')).toHaveText('Billing details saved.')
  await expect(page.getByText('Paid through Razorpay (test mode).')).toBeVisible()
  await expect(page.getByTestId('plan-row').nth(1)).toContainText('₹4,999 a month')
  await page.getByRole('button', { name: 'Switch to Studio' }).click()
  await expect(page.getByTestId('billing-status')).toContainText('You are on Studio.')
  await expect(page.getByTestId('plan-row').nth(1)).toContainText('Your plan')
  await expect(page.getByTestId('invoice-row').first()).toContainText('incl. CGST and SGST')
  if (SHOTS) { await page.waitForTimeout(600); await page.screenshot({ path: `${SHOTS}/g3-billing.png`, fullPage: true }) }
  expect(posts.map((p) => p.split(' ').slice(0, 2).join(' '))).toEqual(['POST /api/billing/topup', 'PUT /api/billing/details', 'POST /api/billing/plan'])
})
