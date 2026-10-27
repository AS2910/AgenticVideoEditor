import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

/** One processing model (2026-10-20), end to end in a real browser: a 5-line
 *  "Go" against a scripted server (no vendor, nothing spent). The server's jobs
 *  advance on a clock from the moment Go is posted; the events channel answers
 *  404 so the editor reads them through GET /jobs?active=1, as it does whenever
 *  the channel is down. SHOTS=<dir> saves screenshots of each stage there. */

const LINE_S = 2.4          // each line: voicing, then the fit check
const RENDER_S = 2.0
const SHOTS = process.env.SHOTS ?? ''

function clip(): Buffer {
  // A 30 s picture with sound, made once; the 2.3 s fixture if ffmpeg is missing.
  const out = join(tmpdir(), 'voltage-e2e-30s.mp4')
  if (!existsSync(out)) {
    try {
      execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=220',
        '-t', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', out])
    } catch {
      return readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
    }
  }
  return readFileSync(out)
}
const MP4 = clip()

const LINES = [
  { text: 'Welcome to the final round of the Riverside Open.', start: 0.5, end: 4.0, speaker: 'A' },
  { text: 'Both fighters trained for this all year.', start: 5.0, end: 9.0, speaker: 'A' },
  { text: 'Here comes the opening bell.', start: 10.0, end: 14.0, speaker: 'A' },
  { text: 'A sharp jab lands early.', start: 15.0, end: 19.0, speaker: 'A' },
  { text: 'The crowd is on its feet.', start: 20.0, end: 24.0, speaker: 'A' },
  { text: 'And that is the decision.', start: 25.0, end: 29.0, speaker: 'A' },
]
const NEW = [
  'Final round, Riverside Open, and the gym is packed.',
  'A whole year of training comes down to this.',
  'Bell rings, and both of them come out fast.',
  'Jab, jab, and a clean right hand lands.',
  'Listen to that crowd.',
]
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 30, container: 'mp4' }
const AT = '2026-10-20T10:00:00Z'
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] }
const take = (k: number) => ({
  candidate_id: `c${k + 1}`, plan: { selection: { start: LINES[k].start, end: LINES[k].end }, new_text: NEW[k], voice_profile_id: 'jeevan', mix: 'replace' },
  audio: { kind: 'audio', sha256: `${k + 1}`.repeat(64), duration: 3, container: 'wav' },
  frames: { kind: 'video', sha256: `f${k + 1}`.padEnd(64, 'f'), duration: 3, container: 'mp4' }, continuity: CONT, fit_notes: [],
})
const ITEM = (k: number, over: Record<string, unknown> = {}) => ({
  item_id: `i${k + 1}`, selection: { start: LINES[k].start, end: LINES[k].end }, old_text: LINES[k].text, new_text: NEW[k], speaker: 'A',
  mix: 'replace', reason: 'Commentary for this moment.', kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null,
  edit_id: null, question: null, error: null, note: null, progress: null, ...over,
})
const QUESTION = { text: 'Voice all five lines in Jeevan’s voice, about $0.09?', options: ['Go, voice all five', 'Not yet'], guess: 'Go, voice all five', gate: true, cost_usd: 0.09, left_usd: 0.5, cap_usd: 0.5 }
const RENDER_FINAL = { kind: 'video', sha256: 'e'.repeat(64), duration: 30, container: 'mp4' }
const RENDER_V2 = { kind: 'video', sha256: 'v'.repeat(64), duration: 30, container: 'mp4' }
const KEPT = { edit_id: 'e1', candidate_id: 'c0', new_text: 'And that settles it.', selection: { start: 25.0, end: 29.0 }, mix: 'replace', overridden: false, reverted: false }

type Mode = 'ok' | 'fail'

/** The scripted server: everything it says is a function of the time since Go. */
class World {
  goAt: number | null = null
  retryAt: number | null = null
  readonly mode: Mode
  constructor(mode: Mode) { this.mode = mode }
  e(now = Date.now()) { return this.goAt === null ? -1 : (now - this.goAt) / 1000 }
  lineJob(k: number) {
    const e = this.e()
    const start = k * LINE_S, end = start + LINE_S
    const iso = (s: number) => new Date(this.goAt! + s * 1000).toISOString()
    const failed = this.mode === 'fail' && k === 2
    const base = { job_id: `J${k + 1}`, video_id: 'p1', turn_id: 'j9', kind: 'voice_line', line_ids: [`i${k + 1}`], created_at: iso(0),
      detail: { text: NEW[k], voice_name: 'Jeevan', chars: NEW[k].length }, cost_usd: null as number | null, retryable: false, error_code: null as string | null, error_text: null as string | null }
    if (e < start) return { ...base, status: 'queued', step_label: 'Queued', progress: 0, started_at: null, finished_at: null, eta_s: Math.ceil(LINE_S) }
    if (e < end) {
      const p = (e - start) / LINE_S
      return { ...base, status: 'running', step_label: p < 0.6 ? 'Voicing' : 'Checking fit', progress: Math.round(p * 100) / 100, started_at: iso(start), finished_at: null, eta_s: Math.max(1, Math.ceil(end - e)) }
    }
    if (failed) return { ...base, status: 'failed', step_label: 'Failed', progress: 1, started_at: iso(start), finished_at: iso(end), eta_s: null, retryable: true, error_code: 'vendor_failed', error_text: 'The voice service did not answer after 3 tries.' }
    return { ...base, status: 'done', step_label: 'Ready to hear', progress: 1, started_at: iso(start), finished_at: iso(end), eta_s: null, cost_usd: 0.018 }
  }
  retryJob() {
    if (this.retryAt === null) return null
    const e = (Date.now() - this.retryAt) / 1000
    const iso = (s: number) => new Date(this.retryAt! + s * 1000).toISOString()
    const base = { job_id: 'J7', video_id: 'p1', turn_id: null, kind: 'voice_line', line_ids: ['i3'], created_at: iso(0), detail: { text: NEW[2], voice_name: 'Jeevan', chars: NEW[2].length, manual: true },
      error_code: null, error_text: null, retryable: false }
    return e < LINE_S
      ? { ...base, status: 'running', step_label: e < LINE_S * 0.6 ? 'Voicing' : 'Checking fit', progress: e / LINE_S, started_at: iso(0), finished_at: null, eta_s: Math.max(1, Math.ceil(LINE_S - e)), cost_usd: null }
      : { ...base, status: 'done', step_label: 'Ready to hear', progress: 1, started_at: iso(0), finished_at: iso(LINE_S), eta_s: null, cost_usd: 0.018 }
  }
  get rendered() { return this.e() >= 5 * LINE_S + RENDER_S }
  readyIds() { return [0, 1, 2, 3, 4].filter((k) => this.lineJob(k).status === 'done' || (k === 2 && this.retryJob()?.status === 'done')).map((k) => `i${k + 1}`) }
  includes() {
    const ids = this.readyIds()
    return { item_ids: ids, candidate_ids: ['c0', ...ids.map((i) => `c${i.slice(1)}`)], edit_ids: ['e1'] }
  }
  renderJob() {
    if (this.goAt === null || this.e() < 5 * LINE_S) return null
    const e = this.e() - 5 * LINE_S
    const iso = (s: number) => new Date(this.goAt! + (5 * LINE_S + s) * 1000).toISOString()
    const base = { job_id: 'J6', video_id: 'p1', turn_id: 'j9', kind: 'render_preview', line_ids: this.readyIds(), created_at: iso(0), cost_usd: null, error_code: null, error_text: null, retryable: false,
      detail: { version: 2, mode: 'proposals', render_id: 'r2', includes: this.includes() } }
    return e < RENDER_S
      ? { ...base, status: 'running', step_label: 'Rendering preview v2', progress: e / RENDER_S, started_at: iso(0), finished_at: null, eta_s: Math.max(1, Math.ceil(RENDER_S - e)) }
      : { ...base, status: 'done', step_label: 'Preview v2 ready', progress: 1, started_at: iso(0), finished_at: iso(RENDER_S), eta_s: null }
  }
  jobs() {
    if (this.goAt === null) return []
    const all = [...[0, 1, 2, 3, 4].map((k) => this.lineJob(k)), this.renderJob(), this.retryJob()].filter(Boolean) as { created_at: string; job_id: string }[]
    return all.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : b.job_id.localeCompare(a.job_id)))
  }
  turn() {
    if (this.goAt === null) return null
    const done = this.rendered
    return { turn_id: 'j9', status: done ? 'done' : 'running', step: done ? 'Done' : 'Voicing the lines', started_at: new Date(this.goAt).toISOString(),
      finished_at: done ? new Date(this.goAt + (5 * LINE_S + RENDER_S) * 1000).toISOString() : null,
      spent_usd: this.mode === 'fail' ? 0.07 : 0.09, lines_voiced: this.readyIds().length, render: done ? { version: 2, mode: 'proposals', render_id: 'r2' } : null }
  }
  plan() {
    if (this.goAt === null) return { type: 'plan', plan_id: 'plan1', goal: 'Commentary for the five moments', summary: '', mode: 'ask', status: 'clarifying', created_at: AT, estimate: { items: 5, voice_characters: 210, usd: 0.09, seconds: 0 }, findings: [], question: QUESTION, answers: [], log: [], spend_usd: 0, items: [0, 1, 2, 3, 4].map((k) => ITEM(k)) }
    const items = [0, 1, 2, 3, 4].map((k) => {
      const j = k === 2 && this.retryJob() ? this.retryJob()! : this.lineJob(k)
      if (j.status === 'running') return ITEM(k, { status: 'working', progress: j.step_label })
      if (j.status === 'done') return ITEM(k, { status: 'ready', candidate: take(k) })
      if (j.status === 'failed') return ITEM(k, { status: 'failed', error: j.error_text })
      return ITEM(k)
    })
    return { type: 'plan', plan_id: 'plan1', goal: 'Commentary for the five moments', summary: '', mode: 'ask', status: this.rendered ? 'done' : 'running', created_at: AT, estimate: { items: 5, voice_characters: 210, usd: 0.09, seconds: 0 }, findings: [], question: null, answers: [], log: [], spend_usd: 0, items }
  }
  latest(mode: string) {
    if (mode === 'final') {
      return { mode, current_hash: 'h1', stale: false, in_progress: null,
        latest: { render_id: 'r1', version: 1, edit_set_hash: 'h1', created_at: AT, mode: 'final', render: RENDER_FINAL, includes: { item_ids: [], candidate_ids: ['c0'], edit_ids: ['e1'] }, manifest: this.manifest('final') } }
    }
    const r = this.renderJob()
    return { mode, current_hash: r ? 'h2' : 'h1', stale: false,
      in_progress: r && r.status === 'running' ? { render_id: 'r2', version: 2, edit_set_hash: 'h2', started_at: r.started_at, eta_s: r.eta_s, job_id: 'J6', includes: this.includes() } : null,
      latest: r && r.status === 'done' ? { render_id: 'r2', version: 2, edit_set_hash: 'h2', created_at: r.finished_at, mode: 'proposals', render: RENDER_V2, includes: this.includes(), manifest: this.manifest('proposals') } : null }
  }
  manifest(mode: string) {
    const v2 = mode === 'proposals'
    return { segments: [], inserts: [], pieces: [], render: v2 ? RENDER_V2 : RENDER_FINAL, proposals: v2 ? this.readyIds() : [], edit_hash: v2 ? 'h2' : 'h1', mode,
      cached: true, version: v2 ? 2 : 1, render_id: v2 ? 'r2' : 'r1', created_at: AT, includes: v2 ? this.includes() : { item_ids: [], candidate_ids: ['c0'], edit_ids: ['e1'] } }
  }
}

async function serve(page: Page, world: World) {
  const project = () => ({
    video_id: 'p1', project_id: null, project_name: null, filename: 'riverside-final-round.mp4', duration: 30, media: MEDIA, created_at: AT,
    consent_granted_at: AT, transcript: LINES.flatMap((l) => l.text.split(' ').map((w, k, ws) => ({ text: w, start: l.start + (k * (l.end - l.start)) / ws.length, end: l.start + ((k + 0.9) * (l.end - l.start)) / ws.length }))),
    statements: LINES, speakers: [{ label: 'A', name: 'Jeevan', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5, more_controls: true },   // run 5 item 5: versions are named under More controls
    plan: world.plan(), reading: { opening: 'One commentator, six lines.', roles: [] }, suggestions: [], frames: [], edits: [KEPT],
    messages: [
      { role: 'user', text: 'Add commentary for the five big moments', kind: 'say', seq: 1 },
      { role: 'assistant', text: 'Five lines, one for each moment, in Jeevan’s voice. Each fits its gap.', kind: 'say', seq: 2 },
    ],
  })
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/videos/p1')) return json(project())
    if (url.includes('/jobs/stop')) return json({ cancelled: 0 })
    if (/\/jobs\/J3\/retry$/.test(url) && method === 'POST') { world.retryAt = Date.now(); return json(world.retryJob(), 202) }
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) {
      const active = url.includes('active=1')
      const jobs = world.jobs() as { status: string }[]
      return json({ jobs: active ? jobs : jobs, turn: world.turn() })
    }
    if (url.endsWith('/jobs/j9')) {
      const t = world.turn()
      const done = t?.status === 'done'
      return json({ job_id: 'j9', kind: 'turn', project_id: 'p1', status: done ? 'succeeded' : 'running', progress: done ? 1 : 0.5, step: done ? 'Done' : 'Voicing the lines', attempts: 1, error: null,
        result: done ? { type: 'turn', plan: world.plan(), reply: 'All five lines are voiced. Hear them With proposals, then Add them.', question: null, spent_usd: t!.spent_usd, turn_usd: t!.spent_usd, render: t!.render } : null })
    }
    if (url.endsWith('/turns') && method === 'POST') {
      world.goAt = Date.now()
      return json({ job_id: 'j9', kind: 'turn', project_id: 'p1', status: 'queued', progress: 0, step: 'Queued', attempts: 0, result: null, error: null }, 202)
    }
    if (url.includes('/plans/plan1')) return json(world.plan())
    if (url.includes('/renders/latest')) return json(world.latest(new URL(url).searchParams.get('mode') ?? 'final'))
    if (url.endsWith('/export') && method === 'POST') {
      const body = JSON.parse(req.postData() ?? '{}') as { with_proposals?: boolean; request_id?: number }
      return json({ ...world.manifest(body.with_proposals ? 'proposals' : 'final'), request_id: body.request_id ?? null })
    }
    if (url.includes('/messages')) {
      const after = Number(new URL(url).searchParams.get('after') ?? 0)
      const said = world.rendered ? [{ role: 'assistant', text: 'All five lines are voiced. Hear them With proposals, then Add them.', kind: 'say', seq: 3 }] : []
      return json(said.filter((m) => m.seq > after))
    }
    if (url.endsWith('/arrangement')) return json(null, 404)
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0.31, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 1.2, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [{ voice_id: 'jeevan', name: 'Jeevan', description: '', gender: 'male', accent: null, age: null }] })
    if (url.includes('/suggestions')) return json({ suggestions: [] })
    return json({})
  })
}

const shot = async (page: Page, name: string) => {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: join(SHOTS, `${name}.png`) })
}
/** With SHOTS set: a frame every half second, for a recording stitched together afterwards. */
function film(page: Page) {
  if (!SHOTS) return async () => {}
  const dir = join(SHOTS, 'frames')
  mkdirSync(dir, { recursive: true })
  let on = true
  let n = 0
  const loop = (async () => {
    while (on) {
      await page.screenshot({ path: join(dir, `f${String(n++).padStart(4, '0')}.png`) }).catch(() => {})
      await page.waitForTimeout(500).catch(() => {})
    }
  })()
  return async () => { on = false; await loop }
}
const chip = (page: Page, k: number) => page.getByRole('listitem', { name: new RegExp(`^Line at 0:${String(Math.floor(LINES[k].start)).padStart(2, '0')}`) }).getByTestId('row-chip')

async function open(page: Page, world: World) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await serve(page, world)
  await page.goto('/#v/p1')
  await expect(page.getByTestId('clarify')).toBeVisible()
}

test.describe('one processing model: a 5-line Go', () => {
  test('Go: the echo at once, the steps in place, the rows through every state, the badge on the new version', async ({ page }) => {
    const world = new World('ok')
    await open(page, world)
    const cut = film(page)
    await expect(page.getByTestId('mode-badge')).toHaveText('Playing v1 · Edited')
    await expect(page.getByTestId('status-text')).toHaveText(/^Up to date · v1/)
    await expect(chip(page, 5)).toHaveText('✓ In the video')
    await expect(chip(page, 0)).toHaveText('Planned')
    await shot(page, '1-asked')

    // The echo: measured in the page, from the click to your words in the thread.
    await page.evaluate(() => {
      const w = window as unknown as { echoMs?: number }
      const log = document.querySelector('[role=log]')!
      const button = [...document.querySelectorAll('[data-testid=clarify] button')].find((b) => b.textContent?.includes('Go, voice all five'))!
      button.addEventListener('click', () => {
        const t0 = performance.now()
        const seen = () => [...log.querySelectorAll('.bubble')].some((b) => b.textContent?.includes('Go, voice all five'))
        if (seen()) { w.echoMs = 0; return }
        new MutationObserver((_, obs) => { if (seen()) { w.echoMs = performance.now() - t0; obs.disconnect() } }).observe(log, { childList: true, subtree: true })
      }, { capture: true })
    })
    await page.getByRole('button', { name: /Go, voice all five/ }).click()
    await expect.poll(() => page.evaluate(() => (window as unknown as { echoMs?: number }).echoMs)).toBeLessThan(100)
    // The card stays, its options off and the pick marked.
    const card = page.getByTestId('clarify')
    await expect(card).toHaveAttribute('data-picked', 'Go, voice all five')
    await expect(card.getByRole('button', { name: /Go, voice all five/ })).toBeDisabled()
    await expect(card.getByTestId('your-pick')).toBeVisible()

    // Queued, then Voicing with its bar, line by line; the strip names the line, the voice and the time.
    await expect(chip(page, 4)).toHaveText('Queued')
    await expect(page.getByTestId('status-text')).toHaveText(/Voicing line 1 of 5 · Jeevan · about \d+ s|Checking fit · line 1 of 5/)
    await expect(chip(page, 0)).toHaveText('Voicing')
    await expect(page.getByTestId('line-progress').first()).toBeVisible()
    await expect(page.getByTestId('turn-step').nth(1)).toHaveText(/Voicing line \d of 5/)
    await shot(page, '2-voicing')
    await expect(chip(page, 0)).toHaveText('Ready to hear')
    await expect(page.getByTestId('turn-step').first()).toHaveText(/Plan ready/)
    // One step list, updated in place: never a second.
    await expect(page.getByTestId('turn-steps')).toHaveCount(1)
    await expect(page.getByTestId('status-text')).toHaveText(/line 3 of 5|line 4 of 5/, { timeout: 12_000 })
    await shot(page, '3-midway')

    // The render: the rows say Rendering, the player says what is coming.
    await expect(page.getByTestId('status-text')).toHaveText(/Rendering preview v2/, { timeout: 15_000 })
    await expect(chip(page, 0)).toHaveText('Rendering')
    await expect(page.getByTestId('render-note')).toHaveText(/v2 rendering…/)
    await shot(page, '4-rendering')

    // Ready: paused, so it swaps in at the playhead; the proposals are In the preview (not yet added); one summary closes the turn.
    await expect(page.getByTestId('mode-badge')).toHaveText('Playing v2 · With proposals', { timeout: 10_000 })
    for (const k of [0, 1, 2, 3, 4]) await expect(chip(page, k)).toHaveText('In the preview')
    await expect(page.getByTestId('turn-summary')).toContainText('Done. 5 lines voiced, v2 is playing. $0.09 spent.')
    await expect(page.getByTestId('turn-summary').getByRole('button', { name: 'Hear changes' })).toBeVisible()
    await expect(page.getByTestId('turn-summary').getByRole('button', { name: 'Undo all' })).toBeVisible()
    await expect(page.getByTestId('turn-step')).toHaveText([/Plan ready$/, /Voiced 5 lines$/, /Fit check$/, /Preview v2 ready$/])
    await expect(page.getByTestId('status-text')).toHaveText(/Ready\. v2 is playing|Up to date · v2/)
    await expect(page.getByRole('button', { name: 'With proposals' })).toHaveAttribute('aria-pressed', 'true')
    await shot(page, '5-done')

    // Activity lists every job, newest first.
    await page.getByTestId('status-strip').getByRole('button', { name: /Open Activity/ }).click()
    await expect(page.getByTestId('activity-job')).toHaveCount(6)
    await expect(page.getByTestId('activity-job').first()).toContainText('Render preview')
    await shot(page, '6-activity')
    await page.waitForTimeout(1500)
    await cut()
  })

  test('a reload mid-job comes back as it was: the strip, the chips, the step list', async ({ page }) => {
    const world = new World('ok')
    await open(page, world)
    await page.getByRole('button', { name: /Go, voice all five/ }).click()
    await expect(chip(page, 1)).toHaveText('Voicing', { timeout: 10_000 })
    await page.reload()
    await expect(page.getByTestId('status-text')).toHaveText(/line \d of 5/)
    await expect(chip(page, 0)).toHaveText('Ready to hear')
    await expect(chip(page, 4)).toHaveText('Queued')
    await expect(page.getByTestId('turn-steps')).toBeVisible()
    await expect(page.getByTestId('turn-step').nth(1)).toHaveText(/Voicing line \d of 5/)
  })

  test('a failed vendor call is Failed with its reason, and Retry works through the same flow', async ({ page }) => {
    const world = new World('fail')
    await open(page, world)
    await page.getByRole('button', { name: /Go, voice all five/ }).click()
    await expect(chip(page, 2)).toHaveText('Failed', { timeout: 15_000 })
    const row = page.getByRole('listitem', { name: /^Line at 0:10/ })
    await expect(row.getByTestId('failed-reason')).toHaveText('The voice service did not answer after 3 tries.')
    await expect(page.getByTestId('toast')).toContainText('A line failed')
    await expect(page.getByTestId('turn-summary')).toContainText('Done. 4 lines voiced, 1 failed', { timeout: 15_000 })
    await row.getByRole('button', { name: 'Retry' }).click()
    await expect(chip(page, 2)).toHaveText('Voicing')
    await expect(chip(page, 2)).toHaveText(/Ready to hear|In the preview|In the video/, { timeout: 10_000 })
  })

  test('one driver at a time: a line Voltage is voicing cannot be voiced by hand until it is done', async ({ page }) => {
    const world = new World('ok')
    await open(page, world)
    await page.getByRole('button', { name: /Go, voice all five/ }).click()
    await expect(chip(page, 3)).toHaveText('Queued')
    await page.getByRole('listitem', { name: /^Line at 0:15/ }).getByRole('button', { name: /A sharp jab/ }).click()
    await expect(page.getByTestId('driven-note')).toHaveText('Voltage is voicing these lines. Wait or Stop.')
    await expect(page.getByRole('button', { name: 'Voice it' })).toBeDisabled()
    await expect(page.getByTestId('turn-summary')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByTestId('driven-note')).toHaveCount(0)
    await page.getByRole('textbox', { name: 'New wording' }).fill('A jab, and another, and the right hand lands.')
    await expect(page.getByRole('button', { name: 'Voice it' })).toBeEnabled()
  })
})
