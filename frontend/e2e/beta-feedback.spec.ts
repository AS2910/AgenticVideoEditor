import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** Rehearsal item 11 in a real browser (API mocked): Help > Send feedback with a message
 *  and a screenshot; the multipart POST carries the route; then the admin page lists it,
 *  links the screenshot and moves its status. At phone width nothing scrolls sideways. */

const SHOTS = process.env.SHOTS ?? ''
const FLAGS = { flags: ['projects.consistency', 'golive.g7', 'golive.g8'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true }
const PNG = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000', 'hex')

async function serve(page: Page, posts: string[], items: Record<string, unknown>[]) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/me/admin') return json({ admin: true })
    if (path === '/api/help') return json([])
    if (path === '/api/beta-feedback') {
      const body = req.postDataBuffer()?.toString('latin1') ?? ''
      posts.push(body)
      items.unshift({ id: 1, owner: 'local', message: 'The pane hid the Add button.', route: '#help', video_id: null, job_id: null, app_version: 'dev',
        user_agent: 'Playwright', screenshot: body.includes('shot.png'), screenshot_type: 'png', status: 'new', status_by: null, status_at: null, created_at: '2026-10-23T10:00:00.000Z' })
      return json({ id: 1, said: 'Thank you. We read every message.' }, 201)
    }
    if (path === '/api/admin/beta-feedback') {
      const want = new URL(req.url()).searchParams.get('status')
      return json({ items: items.filter((i) => !want || i.status === want), counts: { new: items.filter((i) => i.status === 'new').length, seen: items.filter((i) => i.status === 'seen').length, done: 0 } })
    }
    if (path.startsWith('/api/admin/beta-feedback/') && req.method() === 'PUT') {
      items[0] = { ...items[0], status: JSON.parse(req.postData() ?? '{}').status }
      return json(items[0])
    }
    if (path === '/api/admin/audit') return json({ entries: [] })
    if (path === '/api/me/notifications/count') return json({ unread: 0 })
    return json({})
  })
}

test('item 11: send feedback from Help, then an admin sees it and marks it seen', async ({ page }) => {
  const posts: string[] = []
  const items: Record<string, unknown>[] = []
  await page.setViewportSize({ width: 390, height: 900 })
  await serve(page, posts, items)
  await page.goto('/#help')
  await page.getByRole('button', { name: 'Send feedback' }).click()
  const dialog = page.getByTestId('feedback-dialog')
  await expect(dialog.getByTestId('feedback-context')).toContainText('this page (#help)')
  await dialog.getByLabel('Message').fill('The pane hid the Add button.')
  await dialog.getByLabel(/Screenshot/).setInputFiles({ name: 'shot.png', mimeType: 'image/png', buffer: PNG })
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/item11-send-feedback.png` })
  await dialog.getByRole('button', { name: 'Send feedback' }).click()
  await expect(dialog.getByRole('status')).toHaveText('Thank you. We read every message.')
  expect(posts[0]).toContain('The pane hid the Add button.')
  expect(posts[0]).toContain('#help')
  expect(posts[0]).toContain('filename="shot.png"')
  await dialog.getByRole('button', { name: 'Close' }).click()

  await page.goto('/#admin')
  const section = page.getByTestId('admin-beta-feedback')
  const row = section.getByTestId('beta-row')
  await expect(row).toContainText('The pane hid the Add button.')
  await expect(row.getByRole('link', { name: 'Open the screenshot' })).toHaveAttribute('href', '/api/admin/beta-feedback/1/screenshot')
  await row.getByRole('button', { name: 'Mark seen' }).click()
  await expect(section.getByText('Nothing here.')).toBeVisible()          // the New filter is empty now
  await section.getByRole('button', { name: /^Seen/ }).click()
  await expect(section.getByTestId('beta-row')).toContainText('Seen')
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(sideways).toBeLessThanOrEqual(0)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/item11-admin-feedback.png`, fullPage: true })
})
