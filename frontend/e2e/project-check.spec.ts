import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** A2 in a real browser (API mocked, nothing spent): the project check shows
 *  its price before it runs, runs as a job, lists each issue with its videos
 *  and times (links into the editor), ignores one, runs Fix in all one video
 *  after another, and Fix in this video opens the editor at the time.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString()
const STEP_S = 1.2

const FACT = { issue_id: 4, kind: 'fact', message: 'The videos give different percentages: 20% in bhaji-cam-ad.mp4 and shop-tour.mp4; 30% in offer-cut.mp4.', fingerprint: 'fp4', places: [
  { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', t: 3.2, text: 'Get 20% off the Bhaji Cam this Diwali.' },
  { video_id: 'p4', filename: 'shop-tour.mp4', t: 12, text: 'Twenty percent off, 20% today.' },
  { video_id: 'p3', filename: 'offer-cut.mp4', t: 2, text: 'Get 30% off, only this week.' },
] }
const OFFER = { issue_id: 5, kind: 'offer', message: 'One video calls the sale Diwali Dhamaka, another Diwali Bonanza.', fingerprint: 'fp5', places: [
  { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', t: 8, text: 'Join the Diwali Dhamaka sale.' },
  { video_id: 'p3', filename: 'offer-cut.mp4', t: 9.5, text: 'The Diwali Bonanza sale is on.' },
] }
const LINE = { issue_id: 6, kind: 'required_line', message: '“T&C apply” is a required line, and offer-cut.mp4 does not say it.', fingerprint: 'fp6', places: [
  { video_id: 'p3', filename: 'offer-cut.mp4', t: null, text: '' },
] }

class World {
  checkAt: number | null = null
  fixAt: number | null = null
  ignored = new Set<number>()
  e(at: number | null) { return at === null ? -1 : (Date.now() - at) / 1000 }
  check() {
    if (this.checkAt === null) return null
    const running = this.e(this.checkAt) < STEP_S
    return { check_id: 1, project_id: 'f1', mode: 'full', status: running ? 'running' : 'done', job_id: 'J7', trigger: 'user', cost_usd: running ? 0 : 0.0021,
      notes: running ? [] : ['Loudness not checked for shop-tour.mp4: no render measured yet.'], error: null, started_at: new Date(this.checkAt).toISOString(),
      finished_at: running ? null : new Date().toISOString(), previous_finished_at: null,
      job: { job_id: 'J7', video_id: 'f1', kind: 'check', status: running ? 'running' : 'done', step_label: running ? 'Reading what the videos say' : '3 issues found' } }
  }
  page() {
    const check = this.check()
    const issues = check && check.status === 'done' ? [FACT, OFFER, LINE].map((i) => ({ ...i, ignored: this.ignored.has(i.issue_id) })) : []
    return { check, issues, estimate: { usd: 0.0042, label: 'about $0.01', input_tokens: 2600, output_tokens: 400, model: 'claude-haiku-4-5', available: true, why: null },
      fix_run: this.fixRun(), videos: 3 }
  }
  fixRun() {
    if (this.fixAt === null) return null
    const e = this.e(this.fixAt)
    const row = (video_id: string, filename: string, after: number, outcome: string, why: string) => e < after
      ? { video_id, filename, job_id: `J${after}`, status: e < after - STEP_S ? 'queued' : 'running', step: e < after - STEP_S ? 'Queued' : 'Voltage is on it', outcome: null, why: null }
      : { video_id, filename, job_id: `J${after}`, status: 'done', step: 'Done', outcome, why }
    return { run_id: 'x1', issue_id: 5, message: OFFER.message, status: e < 2 * STEP_S ? 'running' : 'finished', started_at: new Date(this.fixAt).toISOString(),
      finished_at: e < 2 * STEP_S ? null : new Date().toISOString(), videos: [
        row('p2', 'bhaji-cam-ad.mp4', STEP_S, 'current', 'Voltage found nothing to change here.'),
        row('p3', 'offer-cut.mp4', 2 * STEP_S, 'proposed', '1 line is ready to hear. Add them in the video.'),
      ] }
  }
  project() {
    return { project_id: 'f1', name: 'Diwali 2026', brief: 'Get 20% off.', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0.12,
      created_at: ago(9), brief_version: 2, brief_edited_by: 'local', brief_edited_at: ago(2), stale_count: 0 }
  }
  videos() {
    return [
      { video_id: 'p2', project_id: 'f1', filename: 'bhaji-cam-ad.mp4', duration: 48.9, created_at: ago(5), edits: 2, state: 'shipped', last_change: '2 lines changed', made_with_brief: 2, brief_changed: false },
      { video_id: 'p3', project_id: 'f1', filename: 'offer-cut.mp4', duration: 31, created_at: ago(5), edits: 1, state: 'shipped', last_change: '1 line changed', made_with_brief: 2, brief_changed: false },
      { video_id: 'p4', project_id: 'f1', filename: 'shop-tour.mp4', duration: 22, created_at: ago(4), edits: 0, state: 'new', last_change: 'Nothing changed yet', made_with_brief: null, brief_changed: false },
    ]
  }
}

async function mockApi(page: Page, world: World, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const path = new URL(url).pathname
    const method = route.request().method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET') posts.push(`${method} ${path} ${route.request().postData() ?? ''}`.trim())
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json({ flags: ['projects.consistency'] })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true })
    if (url.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/projects/f1/check' && method === 'POST') { world.checkAt = Date.now(); return json(world.page(), 202) }
    if (path === '/api/projects/f1/check') return json(world.page())
    const ignore = /\/check\/issues\/(\d+)\/ignore$/.exec(path)
    if (ignore) { world.ignored.add(Number(ignore[1])); return json(world.page()) }
    if (path.endsWith('/check/issues/5/fix-all')) { world.fixAt = Date.now(); return json(world.page(), 202) }
    if (path.endsWith('/check/issues/4/fix')) return json({ video_id: 'p3', job_id: 'J9', t: 2 }, 202)
    if (path === '/api/projects/f1/rules') return json({ rules: [], rules_version: 0 })
    if (path === '/api/projects/f1/brief-update') return json({ run: null })
    if (path === '/api/projects/f1') return json({ project: world.project(), videos: world.videos(), voices: [], files: [], suggestions: [] })
    if (path === '/api/projects') return json({ projects: [world.project()] })
    if (url.includes('/spend')) return json({ project: { spent_usd: 0.12, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos(\?|$)/.test(url)) return json({ videos: world.videos() })
    return json({})
  })
}

test('the project check prices itself, lists issues with times, ignores, fixes in all and opens a video at the time', async ({ page }) => {
  const world = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockApi(page, world, posts)
  await page.goto('/#p/f1')

  const panel = page.getByTestId('project-check')
  await expect(panel).toContainText('Not checked yet')
  await expect(panel.getByTestId('check-cost')).toContainText('the text pass reads the transcripts for about $0.01')
  await expect(panel.getByRole('button', { name: 'Rules only' })).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a2-before.png`, fullPage: true })

  await panel.getByRole('button', { name: 'Check project · about $0.01' }).click()
  expect(posts).toContain('POST /api/projects/f1/check {"mode":"full"}')
  await expect(panel.getByTestId('check-running')).toContainText('Reading what the videos say')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a2-running.png`, fullPage: true })

  await expect(panel.getByTestId('check-issue')).toHaveCount(3, { timeout: 15_000 })
  await expect(panel.getByTestId('check-when')).toContainText('with the text pass, under $0.01')
  await expect(panel).toContainText('Loudness not checked for shop-tour.mp4')
  const fact = panel.getByTestId('check-issue').first()
  await expect(fact).toContainText('20% in bhaji-cam-ad.mp4 and shop-tour.mp4; 30% in offer-cut.mp4')
  await expect(fact.getByRole('link', { name: /bhaji-cam-ad\.mp4 · 0:03/ })).toHaveAttribute('href', '#v/p2@3.2')
  // The first-time tip points at the panel; Got it puts it away.
  await expect(page.getByRole('status', { name: 'Tip: Project check' })).toBeVisible()
  await page.getByRole('button', { name: 'Got it' }).click()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a2-issues.png`, fullPage: true })

  const line = panel.getByTestId('check-issue').nth(2)
  await line.getByRole('button', { name: 'Ignore' }).click()
  await expect(panel.getByTestId('check-issue')).toHaveCount(2)
  await expect(panel.getByRole('button', { name: '1 ignored issue · Show' })).toBeVisible()

  const offer = panel.getByTestId('check-issue').nth(1)
  await offer.getByRole('button', { name: 'Fix in all 2' }).click()
  expect(posts).toContain('POST /api/projects/f1/check/issues/5/fix-all {}')
  const run = panel.getByTestId('check-fix-run')
  await expect(run).toContainText('Fixing in 2 videos')
  await expect(run).toContainText('Fix in all finished', { timeout: 15_000 })
  await expect(run.getByTestId('check-fix-video').nth(0)).toContainText('Nothing to change')
  await expect(run.getByTestId('check-fix-video').nth(1)).toContainText('Ready to review')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a2-fix-all.png`, fullPage: true })

  await panel.getByTestId('check-issue').first().getByRole('button', { name: 'Fix in offer-cut.mp4' }).click()
  expect(posts).toContain('POST /api/projects/f1/check/issues/4/fix {"video_id":"p3"}')
  await expect(page).toHaveURL(/#v\/p3@2$/)
})
