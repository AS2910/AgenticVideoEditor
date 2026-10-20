import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** A1 in a real browser (API mocked, nothing spent): the brief card names its
 *  version and who saved it, History shows a word diff, two videos made with
 *  an older brief carry "Brief changed", and Bring up to date runs them one
 *  after another: the one the change does not touch is current for free, the
 *  other gets a turn and lines to review. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString()
const STEP_S = 1.2

class World {
  startedAt: number | null = null
  e() { return this.startedAt === null ? -1 : (Date.now() - this.startedAt) / 1000 }
  get finished() { return this.e() >= 2 * STEP_S }
  project() {
    return { project_id: 'f1', name: 'Diwali 2026', brief: 'Get 30% off. Say Bhaji Cam as BAH-jee cam.', settings: { autonomy: 'ask', turn_usd: 0.5 },
      ceiling_usd: null, spent_usd: 0.12, created_at: ago(9), brief_version: 4, brief_edited_by: 'local', brief_edited_at: ago(2),
      stale_count: this.finished ? 1 : 2 }
  }
  videos() {
    return [
      { video_id: 'p2', project_id: 'f1', filename: 'bhaji-cam-ad.mp4', duration: 48.9, created_at: ago(5), edits: 2, state: 'shipped', last_change: '2 lines changed', made_with_brief: this.finished ? 4 : 3, brief_changed: !this.finished },
      { video_id: 'p3', project_id: 'f1', filename: 'offer-cut.mp4', duration: 31, created_at: ago(5), edits: 1, state: 'shipped', last_change: '1 line changed', made_with_brief: 3, brief_changed: true },
      { video_id: 'p4', project_id: 'f1', filename: 'shop-tour.mp4', duration: 22, created_at: ago(4), edits: 0, state: 'new', last_change: 'Nothing changed yet', made_with_brief: null, brief_changed: false },
    ]
  }
  run() {
    if (this.startedAt === null) return null
    const e = this.e()
    const first = e < STEP_S
      ? { status: 'running', step: 'Checking what the change touches', outcome: null, why: null }
      : { status: 'done', step: 'Up to date, nothing to change', outcome: 'current', why: 'None of the words the brief changed (20%, 30%) are in this video, so nothing was spent.' }
    const second = e < STEP_S ? { status: 'queued', step: 'Queued', outcome: null, why: null }
      : e < 2 * STEP_S ? { status: 'running', step: 'Voltage is on it', outcome: null, why: null }
        : { status: 'done', step: 'Ready to review', outcome: 'proposed', why: '1 line is ready to hear. Add them in the video.' }
    return { run_id: 'u1', to: 4, status: this.finished ? 'finished' : 'running', started_at: new Date(this.startedAt).toISOString(),
      finished_at: this.finished ? new Date().toISOString() : null, videos: [
        { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', from: 3, job_id: 'J1', ...first },
        { video_id: 'p3', filename: 'offer-cut.mp4', from: 3, job_id: 'J2', ...second },
      ] }
  }
}

async function mockApi(page: Page, world: World, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET') posts.push(`${method} ${new URL(url).pathname}`)
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json({ flags: ['projects.consistency'] })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true })
    if (url.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/projects/f1/briefs')) return json({ current: 4, versions: [
      { project_id: 'f1', version: 4, text: 'Get 30% off. Say Bhaji Cam as BAH-jee cam.', created_by: 'local', created_at: ago(2) },
      { project_id: 'f1', version: 3, text: 'Get 20% off. Say Bhaji Cam as BAH-jee cam.', created_by: 'local', created_at: ago(4) },
    ] })
    if (url.includes('/projects/f1/briefs/diff')) return json({ a: 3, b: 4, changes: [{ op: 'same', text: 'Get ' }, { op: 'removed', text: '20%' }, { op: 'added', text: '30%' }, { op: 'same', text: ' off. Say Bhaji Cam as BAH-jee cam.' }] })
    if (url.endsWith('/projects/f1/brief-update') && method === 'POST') { world.startedAt = Date.now(); return json({ run: world.run() }, 202) }
    if (url.endsWith('/projects/f1/brief-update')) return json({ run: world.run() })
    if (url.endsWith('/projects/f1')) return json({ project: world.project(), videos: world.videos(), voices: [], files: [], suggestions: [] })
    if (url.endsWith('/projects')) return json({ projects: [world.project()] })
    if (url.includes('/spend')) return json({ project: { spent_usd: 0.12, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos(\?|$)/.test(url)) return json({ videos: world.videos() })
    return json({})
  })
}

test('the brief names its version, shows a diff, and brings the older videos up to date', async ({ page }) => {
  const world = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockApi(page, world, posts)
  await page.goto('/#p/f1')

  await expect(page.getByTestId('brief-meta')).toContainText('v4 · edited by you, 2 days ago')
  await expect(page.getByTestId('brief-changed')).toHaveCount(2)
  await expect(page.getByTestId('stale-line')).toContainText('2 videos made with an older brief')
  // The first-time tip points at the line; Got it puts it away.
  await expect(page.getByRole('status', { name: 'Tip: Brief changed' })).toBeVisible()
  await page.getByRole('button', { name: 'Got it' }).click()

  await page.getByRole('button', { name: 'History' }).click()
  const history = page.getByRole('region', { name: 'Brief history' })
  await expect(history.locator('del')).toHaveText('20%')
  await expect(history.locator('ins')).toHaveText('30%')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a1-history.png`, fullPage: true })

  await page.getByRole('button', { name: 'Bring up to date' }).click()
  expect(posts).toContain('POST /api/projects/f1/brief-update')
  const run = page.getByTestId('brief-run')
  await expect(run).toContainText('Bringing 2 videos up to v4')
  await expect(run.getByTestId('brief-run-video').first()).toContainText('Checking what the change touches')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a1-running.png`, fullPage: true })
  await expect(run).toContainText('Brought up to v4', { timeout: 15_000 })
  const rows = run.getByTestId('brief-run-video')
  await expect(rows.nth(0)).toContainText('Up to date')
  await expect(rows.nth(0)).toContainText('so nothing was spent')
  await expect(rows.nth(1)).toContainText('Ready to review')
  // The page reads again when the run ends: the video now current loses its chip.
  await expect(page.getByTestId('brief-changed')).toHaveCount(1)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a1-finished.png`, fullPage: true })
  await run.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByTestId('stale-line')).toContainText('1 video made with an older brief')
})
