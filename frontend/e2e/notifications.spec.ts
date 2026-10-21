import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** G4 in a real browser (API mocked): the bell in the account header shows
 *  the unread count, opens the list, Mark all read clears it, an item opens
 *  where it points; Notification settings save per kind and channel.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const AT = new Date().toISOString()
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse', 'golive.g4'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-home-search', 'first-notifications'], checklist: [], checklist_hidden: true }
const ITEMS = [
  { id: 3, kind: 'spend_alert', title: 'You have used 80% of the ceiling of Diwali ($16 of $20).', body: '', link: '#p/f1', video_id: null, project_id: 'f1', created_at: AT, read: false },
  { id: 2, kind: 'review_comment', title: 'Priya commented on bhaji-cam-ad.mp4 at 0:04.', body: 'Can the price be louder?', link: '#v/p1@4', video_id: 'p1', project_id: 'f1', created_at: AT, read: false },
  { id: 1, kind: 'job_done', title: 'The export of reels-cut.mp4 is done.', body: 'v3 ready', link: '#v/p2', video_id: 'p2', project_id: null, created_at: AT, read: true },
]
const KINDS = [
  { kind: 'job_done', label: 'Long work finished', help: 'An export, a check, a batch or an import that took more than a minute is done.', in_app: true, email: false },
  { kind: 'spend_alert', label: 'Spend alerts', help: 'A video, a project or the month reached 50%, 80% or 100% of its ceiling.', in_app: true, email: true },
]

async function serve(page: Page, writes: string[]) {
  let unread = 2
  let kinds = KINDS
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') writes.push(`${method} ${path} ${req.postData() ?? ''}`.trim())
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/me/notifications/count') return json({ unread })
    if (path === '/api/me/notifications/read') { unread = 0; return json({ unread }) }
    if (path === '/api/me/notifications') return json({ items: ITEMS.map((i) => ({ ...i, read: unread === 0 ? true : i.read })), unread })
    if (path === '/api/me/notifications/settings') {
      if (method === 'PUT') { const body = JSON.parse(req.postData() ?? '{}'); kinds = kinds.map((k) => (body[k.kind] ? { ...k, ...body[k.kind] } : k)) }
      return json({ kinds })
    }
    if (path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/pins') return json({ pins: [] })
    if (path === '/api/projects') return json({ projects: [] })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: [] })
    return json({})
  })
}

test('G4: the bell, mark all read, an item opens, settings save', async ({ page }) => {
  const writes: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, writes)
  await page.goto('/')
  const bell = page.getByRole('button', { name: 'Notifications, 2 unread' })
  await expect(bell).toBeVisible()
  await bell.click()
  const panel = page.getByTestId('bell-panel')
  await expect(panel.getByTestId('bell-item')).toHaveCount(3)
  await expect(panel.getByTestId('bell-item').first()).toContainText('You have used 80% of the ceiling of Diwali')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g4-bell.png` })
  await panel.getByRole('button', { name: 'Mark all read' }).click()
  await expect(page.getByRole('button', { name: 'Notifications', exact: true })).toBeVisible()
  expect(writes).toContain('POST /api/me/notifications/read {"all":true}')
  await panel.getByTestId('bell-item').nth(1).click()
  await expect(page).toHaveURL(/#v\/p1@4$/)

  await page.goto('/#notifications')
  const row = page.getByTestId('notification-kind').filter({ hasText: 'Long work finished' })
  await row.getByRole('switch', { name: 'Long work finished by email' }).click()
  await expect(row.getByRole('switch', { name: 'Long work finished by email' })).toHaveAttribute('aria-checked', 'true')
  expect(writes).toContain('PUT /api/me/notifications/settings {"job_done":{"email":true}}')
  await page.keyboard.press('Escape')
})
