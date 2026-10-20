import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** B2 in a real browser (API mocked, nothing spent): Make language versions
 *  from a video's card (pick Hindi and Tamil, the voice handling, the numbers
 *  first, then Make 2 versions), the master and its versions as one stacked
 *  card with language chips, the batch board naming each version; after the
 *  master ships a change, "Out of sync with master" on the stack, on Home and
 *  in the version's editor header, and Sync this change.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString()

class World {
  made: { video_id: string; language: string; label: string }[] = []
  masterEdited = false
  synced: string[] = []
  outOfSync(id: string) { return this.masterEdited && !this.synced.includes(id) }
  chips() { return this.made.map((c) => ({ video_id: c.video_id, language: c.language, label: c.label, out_of_sync: this.outOfSync(c.video_id) })) }
  videos() {
    const base = { project_id: 'f1', project_name: 'Diwali 2026', duration: 30, created_at: ago(5), edits: 0, state: 'new', last_change: 'Nothing changed yet', stage: 'draft', made_with_brief: null, brief_changed: false }
    return [
      { ...base, video_id: 'p2', filename: 'bhaji-cam.mp4', master_id: null, language: null, language_label: null, out_of_sync: false, languages: this.chips() },
      { ...base, video_id: 'p3', filename: 'shop-tour.mp4', master_id: null, language: null, language_label: null, out_of_sync: false, languages: [] },
      ...this.made.map((c) => ({ ...base, video_id: c.video_id, filename: 'bhaji-cam.mp4', master_id: 'p2', language: c.language, language_label: c.label, out_of_sync: this.outOfSync(c.video_id), languages: [] })),
    ]
  }
  batch() {
    if (this.made.length === 0) return null
    const rows = this.made.map((c, i) => ({ video_id: c.video_id, filename: `bhaji-cam.mp4 · ${c.label}`, stage: 'draft', stage_label: 'Draft', lines: 4, est_usd: 0.12, cap_usd: 0.5,
      job_id: `J${i + 10}`, why: '4 lines are ready to hear.', question: null, ready: 4, spent_usd: 0.11, added: null, answers: [], state: 'ready', label: 'Ready to review' }))
    return { batch_id: 'J9', project_id: 'f1', source: 'language', goal: 'Make Hindi, Tamil versions of bhaji-cam.mp4', phase: 'finished', status: 'done', step: '2 of 2 videos finished',
      created_at: ago(0), started_at: ago(0), finished_at: ago(0), totals: { videos: 2, lines: 8, est_usd: 0.24, est_s: null, cap_usd: 1 }, summary: null, rows, counts: {}, spent_usd: 0.22, can_add: true }
  }
  project() {
    return { project_id: 'f1', name: 'Diwali 2026', brief: 'Bhajicam festive offer.', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0.12,
      created_at: ago(9), brief_version: 1, brief_edited_by: 'local', brief_edited_at: ago(2), stale_count: 0 }
  }
}

const SET = (world: World) => ({
  master_id: 'p2', master_filename: 'bhaji-cam.mp4', original: 'en', original_label: 'English', in_project: true, lines: 4, children: world.chips(),
  options: [['hi', 'Hindi'], ['hinglish', 'Hinglish'], ['ta', 'Tamil'], ['mr', 'Marathi']].map(([code, label]) => ({ code, label, made: world.made.some((m) => m.language === code) })),
})

async function mockApi(page: Page, world: World, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const path = new URL(url).pathname
    const method = route.request().method()
    const body = route.request().postData() ?? ''
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path} ${body}`.trim())
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json({ flags: ['projects.consistency', 'projects.batch'] })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-project-check', 'first-batch'], checklist: [], checklist_hidden: true })
    if (url.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/videos/p2/languages' && method === 'GET') return json(SET(world))
    if (path === '/api/videos/p2/languages') {
      const req = JSON.parse(body)
      const gate = { videos: req.languages.length, lines: 4 * req.languages.length, est_usd: 0.12 * req.languages.length, cap_usd: 0.5 * req.languages.length, per_video_cap_usd: 0.5 }
      if (req.dry_run) return json({ gate, batch_id: null, children: [] }, 201)
      const labels: Record<string, string> = { hi: 'Hindi', ta: 'Tamil', mr: 'Marathi', hinglish: 'Hinglish' }
      world.made = req.languages.map((code: string, i: number) => ({ video_id: `p${6 + i}`, language: code, label: labels[code] }))
      return json({ gate, batch_id: 'J9', children: world.made }, 201)
    }
    const sync = path.match(/^\/api\/videos\/(p\d+)\/sync$/)
    if (sync) { world.synced.push(sync[1]); return json({ job_id: 'T1', lines: [{ edit_id: 'e3', start: 1.2, end: 2.3, what: 'changed', text: 'Now 30% off.' }], to: 12 }, 202) }
    if (path === '/api/projects/f1/batches') return json({ batches: world.batch() ? [world.batch()] : [] })
    if (path === '/api/projects/f1/check') return json({ check: null, issues: [], estimate: { usd: 0, label: 'free', input_tokens: 0, output_tokens: 0, model: '', available: false, why: null }, fix_run: null, videos: 2 })
    if (path === '/api/projects/f1/rules') return json({ rules: [], rules_version: 0 })
    if (path === '/api/projects/f1/brief-update') return json({ run: null })
    if (path.includes('/export-presets')) return json({ presets: [] })
    if (path.includes('/exports')) return json({ exports: [], videos: [], warnings: [] })
    if (path === '/api/projects/f1') return json({ project: world.project(), videos: world.videos(), voices: [], files: [], suggestions: [] })
    if (path === '/api/projects') return json({ projects: [{ ...world.project(), video_count: world.videos().length }] })
    if (url.includes('/spend')) return json({ project: { spent_usd: 0.12, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos(\?|$)/.test(url)) return json({ videos: world.videos() })
    return json({})
  })
}

test('make language versions, see them stacked with chips, then sync a change from the master', async ({ page }) => {
  const world = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockApi(page, world, posts)
  await page.goto('/#p/f1')

  const stackOf = (name: string) => page.getByTestId('video-stack').filter({ has: page.locator('a', { hasText: name }) }).first()
  await stackOf('bhaji-cam.mp4').getByTestId('make-languages').click()
  const dialog = page.getByTestId('language-dialog')
  await expect(dialog).toContainText('this video is in English')
  await expect(dialog.getByTestId('language-gate')).toContainText('Pick a language to see what it costs.')
  await dialog.getByRole('checkbox', { name: /Hindi/ }).check()
  await dialog.getByRole('checkbox', { name: /Tamil/ }).check()
  await expect(dialog.getByRole('radio', { name: /Same voice in the new language/ })).toBeChecked()
  await expect(dialog.getByTestId('language-gate')).toContainText('2 versions · 8 lines · about $0.24')
  await expect(dialog.getByTestId('language-gate')).toContainText('Spends at most $1.00')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b2-dialog.png`, fullPage: true })
  await dialog.getByRole('button', { name: 'Make 2 versions' }).click()
  expect(posts).toContain('POST /api/videos/p2/languages {"languages":["hi","ta"],"voice":"same"}')
  await expect(dialog).toBeHidden()

  // One stacked card: the master with its versions as chips; the versions are not separate cards.
  const versions = page.getByTestId('language-versions')
  await expect(versions.getByRole('link', { name: 'Open the Hindi version' })).toHaveAttribute('href', '#v/p6')
  await expect(versions.getByRole('link', { name: 'Open the Tamil version' })).toBeVisible()
  await expect(versions).toContainText('In step')
  await expect(page.getByTestId('video-stack')).toHaveCount(2)
  const board = page.getByTestId('batch-board')
  await expect(board).toContainText('bhaji-cam.mp4 · Hindi')
  await expect(board).toContainText('bhaji-cam.mp4 · Tamil')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b2-stacked.png`, fullPage: true })

  // The master ships a change: every version is out of sync.
  world.masterEdited = true
  await page.reload()
  await expect(page.getByTestId('language-versions').getByTestId('out-of-sync')).toHaveCount(2)
  await expect(page.getByRole('status', { name: 'Tip: Out of sync' })).toBeVisible()
  await page.getByRole('button', { name: 'Got it' }).click()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b2-out-of-sync.png`, fullPage: true })
  const hindi = page.getByTestId('language-versions').locator('li').filter({ hasText: 'Hindi' })
  await hindi.getByRole('button', { name: 'Sync this change' }).click()
  expect(posts).toContain('POST /api/videos/p6/sync')
  await expect(page.getByTestId('language-versions').getByTestId('out-of-sync')).toHaveCount(1)

  // Home: the master's chips, and the Tamil version marked out of sync.
  await page.goto('/#home')
  await expect(page.getByTestId('language-chips').first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Tamil version, out of sync with master' }).first()).toBeVisible()
  await expect(page.getByTestId('out-of-sync').first()).toContainText('Out of sync with master')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b2-home.png`, fullPage: true })
})
