import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** C1 in a real browser (API mocked, nothing spent): the project page's
 *  Board beside Grid (remembered), a card dragged to Approved (one move, one
 *  event), another moved from the keyboard with Move to, the Activity panel
 *  saying each in a sentence with Show older; then, in the editor, Add it on
 *  an Approved video shows the warning first and adds only on Add anyway.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (min: number) => new Date(now - min * 60_000).toISOString()
const FLAGS = { flags: ['projects.consistency', 'projects.review'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-project-check', 'first-brief-changed'], checklist: [], checklist_hidden: true }

type Ev = { id: number; project_id: string; video_id: string | null; actor_kind: string; actor_name: string; verb: string; target: string; payload: Record<string, unknown>; at: string; you: boolean }

class Board {
  stages: Record<string, string> = { p1: 'draft', p2: 'in_review', p3: 'draft' }
  events: Ev[] = []
  nextId = 50
  constructor() {
    // An older history, so the feed has a second page.
    for (let i = 0; i < 32; i++) this.add({ video_id: 'p3', actor_kind: 'voltage', actor_name: 'Voltage', verb: i % 2 ? 'edit.shipped' : 'brief.saved', payload: { version: i }, at: ago(600 - i), you: false })
    this.add({ video_id: 'p2', actor_kind: 'reviewer', actor_name: 'Priya', verb: 'stage.moved', payload: { from: 'in_review', to: 'changes_asked', why: 'Changes asked by review link.' }, at: ago(30), you: false })
    this.add({ video_id: 'p2', actor_kind: 'user', actor_name: 'local', verb: 'stage.moved', payload: { from: 'changes_asked', to: 'in_review', why: 'Review link sent to Priya.' }, at: ago(20), you: true })
    for (let i = 0; i < 4; i++) this.add({ video_id: 'p2', actor_kind: 'voltage', actor_name: 'Voltage', verb: 'edit.shipped', payload: {}, at: ago(10), you: false })
  }
  add(e: Omit<Ev, 'id' | 'project_id' | 'target'>) { this.events.unshift({ id: this.nextId++, project_id: 'f1', target: e.video_id ?? '', ...e }) }
  page(before: number | null, limit: number) {
    const list = this.events.filter((e) => before === null || e.id < before)
    const events = list.slice(0, limit)
    return { events, next: list.length > limit ? events[events.length - 1].id : null }
  }
  videos() {
    const base = { project_id: 'f1', project_name: 'Diwali 2026', duration: 31, created_at: ago(900), edits: 0, state: 'new', last_change: 'Nothing changed yet', made_with_brief: 1, brief_changed: false, open_comments: 0 }
    return [
      { ...base, video_id: 'p1', filename: 'bhaji-cam-ad.mp4', stage: this.stages.p1 },
      { ...base, video_id: 'p2', filename: 'reels-cut.mp4', stage: this.stages.p2, duration: 15, brief_changed: true, made_with_brief: 0 },
      { ...base, video_id: 'p3', filename: 'promo.mp4', stage: this.stages.p3, duration: 6 },
    ]
  }
  project() {
    return { project_id: 'f1', name: 'Diwali 2026', brief: 'Bhajicam festive offer.', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0.12,
      created_at: ago(900), brief_version: 1, brief_edited_by: 'local', brief_edited_at: ago(120), stale_count: 1 }
  }
}

async function serveProject(page: Page, board: Board, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const body = req.postData() ?? ''
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path} ${body}`.trim())
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    const move = path.match(/^\/api\/videos\/(p\d)\/stage$/)
    if (move && method === 'POST') {
      const to = JSON.parse(body).to as string
      const from = board.stages[move[1]]
      board.stages[move[1]] = to
      board.add({ video_id: move[1], actor_kind: 'user', actor_name: 'local', verb: 'stage.moved', payload: { from, to, why: '' }, at: new Date().toISOString(), you: true })
      return json({ video_id: move[1], stage: to, label: to, moved: from !== to, move: null })
    }
    if (path === '/api/projects/f1/events') return json(board.page(url.searchParams.get('before') ? Number(url.searchParams.get('before')) : null, Number(url.searchParams.get('limit') ?? 30)))
    if (path === '/api/projects/f1/check') return json({ check: null, issues: [], estimate: { usd: 0, label: 'free', input_tokens: 0, output_tokens: 0, model: '', available: false, why: null }, fix_run: null, videos: 3 })
    if (path === '/api/projects/f1/rules') return json({ rules: [], rules_version: 0 })
    if (path === '/api/projects/f1/brief-update') return json({ run: null })
    if (path === '/api/projects/f1') return json({ project: board.project(), videos: board.videos(), voices: [], files: [], suggestions: [] })
    if (path === '/api/projects') return json({ projects: [{ ...board.project(), video_count: 3 }] })
    if (path.includes('/spend')) return json({ project: { spent_usd: 0.12, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: board.videos() })
    return json({})
  })
}

test('the board: Grid or Board, a drag and a keyboard move, each one event, and the feed in sentences', async ({ page }) => {
  const board = new Board()
  const posts: string[] = []
  await page.setViewportSize({ width: 1360, height: 950 })
  await serveProject(page, board, posts)
  await page.goto('/#p/f1')

  // The feed: readable sentences, newest first, a run of lines folded into one.
  const feed = page.getByTestId('feed')
  await expect(feed.getByTestId('feed-item').first()).toHaveText(/Voltage voiced 4 lines in reels-cut/)
  await expect(feed).toContainText('You sent reels-cut for review to Priya')
  await expect(feed).toContainText('Priya asked for changes to reels-cut')

  // Board beside Grid.
  await expect(page.getByRole('group', { name: 'Show videos as' }).getByRole('button', { name: 'Grid' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('group', { name: 'Show videos as' }).getByRole('button', { name: 'Board' }).click()
  await expect(page.getByTestId('board')).toBeVisible()
  await expect(page.getByRole('status', { name: 'Tip: Board' })).toBeVisible()
  await page.getByRole('status', { name: 'Tip: Board' }).getByRole('button', { name: 'Got it' }).click()
  await expect(page.getByRole('region', { name: 'Draft, 2 videos' })).toBeVisible()
  await expect(page.getByTestId('column-in_review').getByTestId('brief-changed')).toHaveText('Brief changed')
  await expect(page.getByTestId('column-in_review').getByTestId('open-comments')).toHaveText('0 open comments')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c1-board.png`, fullPage: true })

  // Drag bhaji-cam-ad to Approved: one POST, one event, the feed says it.
  const card = page.getByTestId('board-card').filter({ hasText: 'bhaji-cam-ad.mp4' })
  await card.dragTo(page.getByTestId('column-approved'))
  await expect(page.getByTestId('column-approved')).toContainText('bhaji-cam-ad.mp4')
  expect(posts.filter((p) => p.includes('/stage'))).toEqual(['POST /api/videos/p1/stage {"to":"approved"}'])
  await expect(feed.getByTestId('feed-item').first()).toHaveText(/You moved bhaji-cam-ad to Approved/)
  expect(board.events.filter((e) => e.verb === 'stage.moved' && e.video_id === 'p1')).toHaveLength(1)

  // The keyboard: Move to on promo, arrow to Changes asked, Enter.
  await page.getByRole('button', { name: 'Move promo.mp4 to another stage' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('menuitem', { name: 'In review' })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('column-changes_asked')).toContainText('promo.mp4')
  expect(posts.filter((p) => p.includes('/stage'))).toEqual(['POST /api/videos/p1/stage {"to":"approved"}', 'POST /api/videos/p3/stage {"to":"changes_asked"}'])
  await expect(feed.getByTestId('feed-item').first()).toHaveText(/You moved promo to Changes asked/)

  // Older activity on ask.
  const before = await feed.getByTestId('feed-item').count()
  await feed.getByRole('button', { name: 'Show older' }).click()
  await expect.poll(() => feed.getByTestId('feed-item').count()).toBeGreaterThan(before)
  await expect(feed.getByRole('button', { name: 'Show older' })).toBeHidden()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c1-feed.png`, fullPage: true })

  // The choice is remembered.
  await page.reload()
  await expect(page.getByTestId('board')).toBeVisible()
})

// ── the editor: Add it on an Approved video ──────────────────────────────────

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const AT = '2026-10-20T10:00:00Z'
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4' }
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] }
const LINE = { text: 'Get thirty percent off today.', start: 0.2, end: 2.0, speaker: 'A' }
const TAKE = { candidate_id: 'c1', plan: { selection: { start: 0.2, end: 2.0 }, new_text: 'Now forty percent off today.', voice_profile_id: 'jeevan', mix: 'replace' },
  audio: { kind: 'audio', sha256: '1'.repeat(64), duration: 1.8, container: 'wav' }, frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 1.8, container: 'mp4' }, continuity: CONT, fit_notes: [] }

test('the editor warns before Add it on an Approved video, and adds only on Add anyway', async ({ page }) => {
  let stage = 'approved'
  let added = false
  const approves: string[] = []
  const item = () => ({ item_id: 'i1', selection: { start: 0.2, end: 2.0 }, old_text: LINE.text, new_text: TAKE.plan.new_text, speaker: 'A', mix: 'replace', reason: 'The new offer.',
    kind: 'planned', enabled: true, status: added ? 'approved' : 'ready', fit: null, candidate: TAKE, edit_id: added ? 'e1' : null, question: null, error: null, note: null, progress: null })
  const plan = () => ({ type: 'plan', plan_id: 'plan1', goal: 'The new offer', summary: '', mode: 'ask', status: 'done', created_at: AT, estimate: { items: 1, voice_characters: 30, usd: 0.01, seconds: 0 },
    findings: [], question: null, answers: [], log: [], spend_usd: 0.01, items: [item()] })
  const video = () => ({
    video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 2.3, media: MEDIA, created_at: AT, consent_granted_at: AT, stage,
    brief_version: 1, made_with_brief: 1, brief_changed: false,
    transcript: LINE.text.split(' ').map((w, k, ws) => ({ text: w, start: LINE.start + (k * (LINE.end - LINE.start)) / ws.length, end: LINE.start + ((k + 0.9) * (LINE.end - LINE.start)) / ws.length })),
    statements: [LINE], speakers: [{ label: 'A', name: 'Jeevan', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
    plan: plan(), reading: { opening: 'One speaker, one line.', roles: [] }, suggestions: [], frames: [],
    edits: added ? [{ edit_id: 'e1', candidate_id: 'c1', new_text: TAKE.plan.new_text, selection: TAKE.plan.selection, mix: 'replace', overridden: false, reverted: false }] : [],
    messages: [{ role: 'user', text: 'Make it forty percent', kind: 'say', seq: 1 }, { role: 'assistant', text: 'One line, ready to hear.', kind: 'say', seq: 2 }],
  })
  const manifest = { segments: [], inserts: [], pieces: [], render: { kind: 'video', sha256: 'e'.repeat(64), duration: 2.3, container: 'mp4' }, proposals: [], edit_hash: 'h1', mode: 'final',
    cached: true, version: 1, render_id: 'r1', created_at: AT, includes: { item_ids: [], candidate_ids: [], edit_ids: [] } }
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json(FLAGS)
    if (url.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/videos/p1')) return json(video())
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) return json({ jobs: [], turn: null })
    if (url.endsWith('/plans/plan1/approve') && method === 'POST') {
      const body = JSON.parse(req.postData() ?? '{}') as { confirm_stage?: boolean }
      approves.push(req.postData() ?? '')
      if (stage === 'approved' && !body.confirm_stage) return json({ detail: { code: 'stage_approved', message: 'This video is Approved. Adding this moves it back to Draft.', videos: ['p1'], options: ['Add anyway', 'Cancel'] } }, 409)
      added = true
      stage = 'draft'
      return json({ approved: [{ item_id: 'i1', edit_id: 'e1', overridden: false, speaker: 'A', voice_profile_id: 'jeevan' }], skipped: [], export: manifest, plan: plan() })
    }
    if (url.includes('/plans/plan1')) return json(plan())
    if (url.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
    if (url.endsWith('/export') && method === 'POST') return json({ ...manifest, request_id: null })
    if (url.includes('/messages')) return json([])
    if (url.endsWith('/projects/f1/rules')) return json({ rules: [], rules_version: 0 })
    if (url.endsWith('/arrangement')) return json(null, 404)
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [{ project_id: 'f1', name: 'Diwali 2026', brief: '', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0, created_at: AT, video_count: 1 }] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0.01, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 1.2, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [{ voice_id: 'jeevan', name: 'Jeevan', description: '', gender: 'male', accent: null, age: null }] })
    if (url.includes('/suggestions')) return json({ suggestions: [] })
    return json({})
  })
  await page.setViewportSize({ width: 1360, height: 950 })
  await page.goto('/#v/p1')
  const addIt = page.getByRole('button', { name: /^Add it/ }).first()
  await expect(addIt).toBeVisible()
  await addIt.click()
  const warning = page.getByTestId('stage-warning')
  await expect(warning).toContainText('This video is Approved. Adding this moves it back to Draft.')
  expect(approves).toEqual([])                                            // nothing sent before the answer
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c1-editor-warning.png` })
  await warning.getByRole('button', { name: 'Cancel' }).click()
  await expect(warning).toBeHidden()
  expect(approves).toEqual([])
  await addIt.click()
  await page.getByTestId('stage-warning').getByRole('button', { name: 'Add anyway' }).click()
  await expect.poll(() => approves.length).toBe(1)
  expect(JSON.parse(approves[0])).toMatchObject({ items: ['i1'], confirm_stage: true })
  await expect(page.getByTestId('stage-warning')).toBeHidden()
})
