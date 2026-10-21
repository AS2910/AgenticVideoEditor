import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** G7 in a real browser (API mocked): Settings shows Admin to an admin; the page draws the
 *  funnel, take acceptance, cost per exported minute, vendor quality ("not measured yet")
 *  and the counts; opening it and the bell post client events. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse', 'golive.g4', 'golive.g7'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true }
const FUNNEL = [['signed_up', 'Signed up', 12], ['first_sign_in', 'Signed in', 12], ['video_uploaded', 'Uploaded a video', 9], ['first_turn', 'Asked Voltage', 7],
  ['take_voiced', 'Got a take', 6], ['take_added', 'Added a take', 4], ['first_export', 'Exported', 3]].map(([step, label, owners]) => ({ step, label, owners, share: (owners as number) / 12 }))
const DATA = {
  funnel: FUNNEL,
  take_acceptance: { voiced: 40, added: 22, rate: 0.55 },
  cost_per_exported_minute: { cost_usd: 6.4, minutes: 8, per_minute: 0.8 },
  vendor_quality: [{ vendor: 'elevenlabs', takes: 40, sim_o: null, sim_o_takes: 0, utmos: null, utmos_takes: 0, measured: false }],
  counts: [{ name: 'take_voiced', source: 'server', count: 40, owners: 6, last: '' }, { name: 'edit.shipped', source: 'server', count: 22, owners: 4, last: '' },
    { name: 'bell.opened', source: 'client', count: 5, owners: 2, last: '' }],
}

async function serve(page: Page, events: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path === '/api/analytics/events') { events.push(JSON.parse(req.postData() ?? '{}').name); return route.fulfill({ status: 204, body: '' }) }
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/me/admin') return json({ admin: true })
    if (path === '/api/admin/analytics') return json(DATA)
    if (path === '/api/me/notifications/count') return json({ unread: 0 })
    if (path === '/api/me/notifications') return json({ items: [], unread: 0 })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    return json({})
  })
}

test('G7: an admin opens the admin page from Settings; events post', async ({ page }) => {
  const events: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, events)
  await page.goto('/#notifications')
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Admin' }).click()
  await expect(page).toHaveURL(/#admin$/)
  await expect(page.getByTestId('funnel-step')).toHaveCount(7)
  await expect(page.getByTestId('funnel-step').last()).toContainText('Exported')
  await expect(page.getByTestId('admin-acceptance')).toContainText('55%')
  await expect(page.getByTestId('admin-cost')).toContainText('$0.80')
  await expect(page.getByTestId('vendor-row')).toContainText('SIM-o not measured yet')
  await expect(page.getByTestId('count-row')).toHaveCount(3)
  if (SHOTS) { await page.waitForTimeout(800); await page.screenshot({ path: `${SHOTS}/g7-admin.png`, fullPage: true }) }
  await page.getByRole('button', { name: /^Notifications/ }).click()
  // (React's dev StrictMode runs a mount effect twice; production posts once.)
  await expect.poll(() => [...new Set(events)]).toEqual(['admin.opened', 'bell.opened'])
})
