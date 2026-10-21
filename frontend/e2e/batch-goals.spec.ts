import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** B1 in a real browser (API mocked, nothing spent): Ask Voltage about all
 *  videos with the picker (every video ticked, each with its stage), one gate
 *  card with the totals and the cap, Go, a board where the rows move from
 *  Queued and Working to Ready to review, Nothing to change, Failed and
 *  Waiting on you; an answer from the board; Add all that passed and one
 *  video's Undo; and Fix in all from the check opening the same gate.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString()
const STEP_S = 1.0

const VIDEOS = [
  { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', stage: 'draft' },
  { video_id: 'p3', filename: 'offer-cut.mp4', stage: 'approved' },
  { video_id: 'p4', filename: 'shop-tour.mp4', stage: 'draft' },
  { video_id: 'p5', filename: 'reel-cut.mp4', stage: 'in_review' },
]
const STAGE: Record<string, string> = { draft: 'Draft', approved: 'Approved', in_review: 'In review' }
const LABEL: Record<string, string> = { planned: 'Planned', queued: 'Queued', working: 'Working', ready: 'Ready to review', nothing: 'Nothing to change', failed: 'Failed', waiting: 'Waiting on you', added: 'Added' }
const FACT = { issue_id: 4, kind: 'fact', message: 'The videos give different percentages: 20% in bhaji-cam-ad.mp4; 30% in offer-cut.mp4.', fingerprint: 'fp4', ignored: false, places: [
  { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', t: 3.2, text: 'Get 20% off.' },
  { video_id: 'p3', filename: 'offer-cut.mp4', t: 2, text: 'Get 30% off.' },
] }

class World {
  picked: string[] = []
  source: 'ask' | 'fix' = 'ask'
  goal = ''
  phase: 'none' | 'gate' | 'running' | 'cancelled' = 'none'
  goAt: number | null = null
  answered = false
  added = false
  undone = false
  e() { return this.goAt === null ? -1 : (Date.now() - this.goAt) / 1000 }
  rowState(id: string, i: number): { state: string; why: string | null; question?: unknown } {
    if (this.phase === 'gate') return { state: 'planned', why: null }
    const e = this.e()
    const start = Math.floor(i / 3) * STEP_S
    if (e < start) return { state: 'queued', why: null }
    if (e < start + STEP_S) return { state: 'working', why: 'Voltage is on it' }
    if (id === 'p2') return this.added && !this.undone ? { state: 'added', why: '1 line added.' } : { state: 'ready', why: '1 line is ready to hear.' }
    if (id === 'p3') return { state: 'nothing', why: 'Voltage found nothing to change here.' }
    if (id === 'p4') return { state: 'failed', why: 'Voltage is still on the last thing you said.' }
    return this.answered ? { state: 'ready', why: '1 line is ready to hear.' } : { state: 'waiting', why: null, question: { text: 'This reel says 25%. Change it to 30% too?', options: ['Change it', 'Leave it'] } }
  }
  batch() {
    if (this.phase === 'none') return null
    const rows = this.picked.map((id, i) => {
      const v = VIDEOS.find((x) => x.video_id === id)!
      const s = this.rowState(id, i)
      return { video_id: id, filename: v.filename, stage: v.stage, stage_label: STAGE[v.stage], lines: id === 'p3' ? 0 : 1, est_usd: 0.05, cap_usd: 0.5, job_id: `J${i + 10}`,
        why: s.why, question: s.question ?? null, ready: s.state === 'ready' ? 1 : 0, spent_usd: s.state === 'queued' || s.state === 'planned' ? 0 : 0.03,
        added: this.added && id === 'p2' ? { edit_ids: ['e7'], at: ago(0), undone_at: this.undone ? ago(0) : null } : null, answers: [], state: s.state, label: LABEL[s.state] }
    })
    const over = rows.every((r) => !['queued', 'working', 'planned'].includes(r.state))
    const phase = this.phase === 'gate' ? 'gate' : this.phase === 'cancelled' ? 'cancelled' : over ? 'finished' : 'running'
    const n = rows.filter((r) => !['queued', 'working'].includes(r.state)).length
    return { batch_id: 'J9', project_id: 'f1', source: this.source, goal: this.goal, phase, status: phase === 'gate' ? 'queued' : over ? 'done' : 'running',
      step: `${n} of ${rows.length} videos finished`, created_at: ago(0), started_at: this.goAt ? new Date(this.goAt).toISOString() : null, finished_at: null,
      totals: { videos: rows.length, lines: rows.reduce((a, r) => a + (r.lines ?? 0), 0), est_usd: 0.42, est_s: 120, cap_usd: 0.5 * rows.length },
      summary: null, rows, counts: {}, spent_usd: rows.reduce((a, r) => a + r.spent_usd, 0), can_add: rows.some((r) => r.state === 'ready') }
  }
  project() {
    return { project_id: 'f1', name: 'Diwali 2026', brief: 'Get 20% off.', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0.12,
      created_at: ago(9), brief_version: 2, brief_edited_by: 'local', brief_edited_at: ago(2), stale_count: 0 }
  }
  videos() {
    return VIDEOS.map((v) => ({ ...v, project_id: 'f1', duration: 30, created_at: ago(5), edits: 0, state: 'new', last_change: 'Nothing changed yet', made_with_brief: null, brief_changed: false }))
  }
}

async function mockApi(page: Page, world: World, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const path = new URL(url).pathname
    const method = route.request().method()
    const body = route.request().postData() ?? ''
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path} ${body}`.trim())
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json({ flags: ['projects.consistency', 'projects.check', 'projects.batch'] })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-project-check'], checklist: [], checklist_hidden: true })
    if (url.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/projects/f1/batches' && method === 'POST') {
      const req = JSON.parse(body)
      world.source = req.source
      world.picked = req.video_ids ?? VIDEOS.map((v) => v.video_id)
      world.goal = req.source === 'fix' ? FACT.message : req.goal
      world.phase = 'gate'
      return json(world.batch(), 201)
    }
    if (path === '/api/projects/f1/batches') return json({ batches: world.batch() ? [world.batch()] : [] })
    if (path.endsWith('/batches/J9/go')) { world.phase = 'running'; world.goAt = Date.now(); return json(world.batch(), 202) }
    if (path.endsWith('/batches/J9/cancel')) { world.phase = 'cancelled'; return json(world.batch()) }
    if (path.endsWith('/videos/p5/answer')) { world.answered = true; return json(world.batch(), 202) }
    if (path.endsWith('/batches/J9/add-all')) { world.added = true; return json(world.batch()) }
    if (path.endsWith('/videos/p2/undo-add')) { world.undone = true; return json(world.batch()) }
    if (path === '/api/projects/f1/check') return json({ check: { check_id: 1, project_id: 'f1', mode: 'rules', status: 'done', job_id: 'J7', trigger: 'user', cost_usd: 0, notes: [], error: null,
      started_at: ago(0), finished_at: ago(0), previous_finished_at: null }, issues: [FACT], estimate: { usd: 0, label: 'free', input_tokens: 0, output_tokens: 0, model: '', available: false, why: null }, fix_run: null, videos: 4 })
    if (path === '/api/projects/f1/rules') return json({ rules: [], rules_version: 0 })
    if (path === '/api/projects/f1/brief-update') return json({ run: null })
    if (path === '/api/projects/f1') return json({ project: world.project(), videos: world.videos(), voices: [], files: [], suggestions: [] })
    if (path === '/api/projects') return json({ projects: [world.project()] })
    if (url.includes('/spend')) return json({ project: { spent_usd: 0.12, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos(\?|$)/.test(url)) return json({ videos: world.videos() })
    return json({})
  })
}

test('a batch goal: pick videos, one gate, Go, every row state, an answer, add all that passed and one undo', async ({ page }) => {
  const world = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockApi(page, world, posts)
  await page.goto('/#p/f1')

  const panel = page.getByTestId('batch')
  const picker = panel.getByTestId('batch-picker')
  await expect(picker.getByRole('checkbox')).toHaveCount(4)
  await expect(picker).toContainText('4 of 4 videos')
  await expect(picker).toContainText('Approved')
  await expect(picker).toContainText('In review')
  await panel.getByLabel('What to change in every video').fill('Make every offer line say 30% off')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b1-ask.png`, fullPage: true })
  await panel.getByRole('button', { name: 'Plan it for 4 videos' }).click()
  expect(posts).toContain('POST /api/projects/f1/batches {"source":"ask","goal":"Make every offer line say 30% off","video_ids":["p2","p3","p4","p5"]}')

  const gate = panel.getByTestId('batch-gate')
  await expect(gate.getByTestId('batch-totals')).toHaveText('4 videos · 3 lines · about $0.42 · about 2 min')
  await expect(gate.getByTestId('batch-cap')).toContainText('Spends at most $2.00')
  await expect(gate).toContainText('nothing to change')
  if (SHOTS) { await page.waitForTimeout(1000); await page.screenshot({ path: `${SHOTS}/b1-gate.png`, fullPage: true }) }
  await gate.getByRole('button', { name: 'Go' }).click()

  const board = panel.getByTestId('batch-board')
  await expect(board.locator('[data-state="working"]')).toHaveCount(3)
  await expect(board.locator('[data-state="queued"]')).toHaveCount(1)
  await expect(board.getByRole('button', { name: 'Cancel the rest' })).toBeVisible()
  await expect(page.getByRole('status', { name: 'Tip: Batch' })).toBeVisible()
  await page.getByRole('button', { name: 'Got it' }).click()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b1-working.png`, fullPage: true })

  await expect(board).toContainText('Batch finished', { timeout: 15_000 })
  const row = (id: string) => board.getByTestId('batch-row').filter({ has: page.locator(`a[href="#v/${id}"]`) })
  await expect(row('p2')).toHaveAttribute('data-state', 'ready')
  await expect(row('p3')).toHaveAttribute('data-state', 'nothing')
  await expect(row('p4')).toHaveAttribute('data-state', 'failed')
  await expect(row('p4')).toContainText('Voltage is still on the last thing you said.')
  await expect(row('p5')).toHaveAttribute('data-state', 'waiting')
  await expect(row('p5').getByTestId('batch-question')).toContainText('This reel says 25%. Change it to 30% too?')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b1-board.png`, fullPage: true })

  await row('p5').getByLabel('Your answer for reel-cut.mp4').fill('Change it to 30%')
  await row('p5').getByRole('button', { name: 'Answer' }).click()
  expect(posts).toContain('POST /api/projects/f1/batches/J9/videos/p5/answer {"text":"Change it to 30%"}')
  await expect(row('p5')).toHaveAttribute('data-state', 'ready')

  await board.getByRole('button', { name: 'Add all that passed · 2 videos' }).click()
  expect(posts).toContain('POST /api/projects/f1/batches/J9/add-all')
  await expect(row('p2')).toHaveAttribute('data-state', 'added')
  await row('p2').getByRole('button', { name: 'Undo the line added here' }).click()
  expect(posts).toContain('POST /api/projects/f1/batches/J9/videos/p2/undo-add')
  await expect(row('p2')).toContainText('Undone. The lines are back as proposals.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b1-added.png`, fullPage: true })
  await expect(row('p2').getByRole('link', { name: 'bhaji-cam-ad.mp4' })).toHaveAttribute('href', '#v/p2')
})

test('Fix in all from the project check opens the batch gate for that issue', async ({ page }) => {
  const world = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockApi(page, world, posts)
  await page.goto('/#p/f1')
  const check = page.getByTestId('project-check')
  await check.getByRole('button', { name: 'Fix in all 2' }).click()
  expect(posts).not.toContain('POST /api/projects/f1/check/issues/4/fix-all {}')
  const gate = page.getByTestId('batch-gate')
  await expect(gate).toContainText(`Fix: ${FACT.message}`)
  await expect(gate.getByTestId('batch-totals')).toHaveText('2 videos · 1 line · about $0.42 · about 2 min')
  expect(posts).toContain('POST /api/projects/f1/batches {"source":"fix","issue_id":4,"video_ids":["p2","p3"]}')
  await gate.getByRole('button', { name: 'Not yet' }).click()
  await expect(page.getByTestId('batch-picker')).toBeVisible()
})
