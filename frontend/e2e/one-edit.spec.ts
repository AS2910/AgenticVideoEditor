import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** One edit at a time per video (2026-10-25), in a real browser against a scripted server (no
 *  vendor, nothing spent): two quick Adds (the first runs, the second waits in Up next, both land
 *  in order), and Stop during an Add (the edit set goes back to what it was before the click). The
 *  events channel answers 404, so the editor reads the lock through GET /jobs?active=1. */

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const RENDER_S = 2.5
const AT = '2026-10-25T10:00:00Z'
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 30, container: 'mp4' }
const LINES = [
  { text: 'Our bread is baked every day.', start: 1.0, end: 4.0, speaker: 'A' },
  { text: 'Come in before nine.', start: 6.0, end: 9.0, speaker: 'A' },
]
const NEW = ['Fresh every morning.', 'Doors open at seven.']
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody'] }
const take = (k: number) => ({
  candidate_id: `c${k + 1}`, plan: { selection: { start: LINES[k].start, end: LINES[k].end }, new_text: NEW[k], voice_profile_id: 'mock', mix: 'replace' },
  audio: { kind: 'audio', sha256: `${k + 1}`.repeat(64), duration: 3, container: 'wav' },
  frames: { kind: 'video', sha256: `f${k + 1}`.padEnd(64, 'f'), duration: 3, container: 'mp4' }, continuity: CONT, fit_notes: [],
})

/** An Add (its render holds the video), or a Voltage turn (addendum 3: two tabs racing to start one). */
interface Add { job: string; items: number[]; at: number; tab: string | null; status: 'running' | 'done' | 'cancelled'; seconds: number; turn?: string }

/** The scripted server: Adds render for RENDER_S seconds while they hold the video; Up next runs after. */
class World {
  adds: Add[] = []
  queue: { id: number; label: string; items: number[]; goal?: string }[] = []
  added = new Set<number>()
  messages: { role: string; text: string; kind: string; seq: number }[] = []
  tick() {
    for (const a of this.adds) {
      if (a.status === 'running' && Date.now() - a.at >= a.seconds * 1000) {
        a.status = 'done'
        const next = this.queue.shift()
        if (next) this.start(next.items, null, RENDER_S, next.goal)
      }
    }
  }
  running() { return this.adds.find((a) => a.status === 'running') ?? null }
  start(items: number[], tab: string | null, seconds = RENDER_S, turn?: string) {
    for (const k of items) this.added.add(k)
    const a: Add = { job: turn ? `T${this.adds.length + 1}` : `J${this.adds.length + 1}`, items, at: Date.now(), tab, status: 'running', seconds, turn }
    this.adds.push(a)
    return a
  }
  lock() {
    const a = this.running()
    if (a?.turn) {
      return { video_id: 'p1', holder: `turn:${a.job}`, action: 'Voltage is planning', started_by: 'local', started_by_name: 'You', tab: a.tab,
        started_at: new Date(a.at).toISOString(), stoppable: true, waiting: false, lease_expires_at: AT }
    }
    return a ? { video_id: 'p1', holder: a.job, action: `Adding '${NEW[a.items[0]].replace(/\.$/, '')}'`, started_by: 'local', started_by_name: 'You', tab: a.tab,
      started_at: new Date(a.at).toISOString(), stoppable: true, waiting: false, lease_expires_at: AT } : null
  }
  /** A turn as GET /jobs/{id} answers it. */
  turnJob(a: Add) {
    const done = a.status !== 'running'
    return { job_id: a.job, kind: 'turn', project_id: 'p1', status: done ? 'succeeded' : 'running', progress: done ? 1 : 0.5, step: done ? 'Done' : 'Thinking',
      attempts: 0, error: null, result: done ? { type: 'turn', plan: this.plan(), reply: 'Done.', question: null } : null }
  }
  job(a: Add) {
    const iso = new Date(a.at).toISOString()
    const base = { job_id: a.job, video_id: 'p1', turn_id: null, kind: 'render_preview', line_ids: a.items.map((k) => `e${k + 1}`), created_at: iso, started_at: iso,
      cost_usd: null, error_code: null, error_text: null, retryable: false, detail: { mode: 'final', added: true, version: this.adds.indexOf(a) + 2 } }
    if (a.status === 'running') return { ...base, status: 'running', step_label: 'Rendering preview', progress: 0.5, finished_at: null, eta_s: 2 }
    return { ...base, status: a.status, step_label: a.status === 'done' ? 'Ready' : 'Stopped', progress: 1, finished_at: iso, eta_s: null }
  }
  items() {
    return [0, 1].map((k) => ({
      item_id: `i${k + 1}`, selection: { start: LINES[k].start, end: LINES[k].end }, old_text: LINES[k].text, new_text: NEW[k], speaker: 'A', mix: 'replace',
      reason: 'Warmer.', kind: 'planned', enabled: true, status: this.added.has(k) ? 'approved' : 'ready', fit: 'fit', candidate: take(k),
      edit_id: this.added.has(k) ? `e${k + 1}` : null, question: null, error: null, note: null, progress: null,
    }))
  }
  plan() {
    return { type: 'plan', plan_id: 'plan1', goal: 'Warmer lines', summary: '', mode: 'draft', status: 'done', created_at: AT, estimate: { items: 0, voice_characters: 0, usd: 0, seconds: 0 },
      findings: [], question: null, answers: [], log: [], spend_usd: 0, items: this.items() }
  }
  edits() {
    return [...this.added].sort().map((k) => ({ edit_id: `e${k + 1}`, candidate_id: `c${k + 1}`, new_text: NEW[k], selection: { start: LINES[k].start, end: LINES[k].end }, mix: 'replace', overridden: false, reverted: false }))
  }
  manifest() {
    const ids = this.edits().map((e) => e.edit_id)
    const v = this.adds.filter((a) => a.status === 'done').length + 1
    return { segments: [], inserts: [], pieces: [], render: { kind: 'video', sha256: `${v}`.repeat(64).slice(0, 64), duration: 30, container: 'mp4' }, proposals: [], edit_hash: `h${v}`, mode: 'final',
      cached: true, version: v, render_id: `r${v}`, created_at: AT, includes: { item_ids: [], candidate_ids: ids.map((e) => `c${e.slice(1)}`), edit_ids: ids } }
  }
}

async function serve(page: Page, world: World) {
  await page.route('**/api/**', async (route: Route) => {
    world.tick()
    const req = route.request()
    const url = req.url()
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/videos/p1')) {
      return json({ video_id: 'p1', project_id: null, project_name: null, filename: 'bakery.mp4', duration: 30, media: MEDIA, created_at: AT, consent_granted_at: AT,
        transcript: LINES.flatMap((l) => l.text.split(' ').map((w, k, ws) => ({ text: w, start: l.start + (k * (l.end - l.start)) / ws.length, end: l.start + ((k + 0.9) * (l.end - l.start)) / ws.length }))),
        statements: LINES, speakers: [{ label: 'A', name: 'Asha', voice_id: null }], settings: { autonomy: 'draft', turn_usd: 0.5 },
        plan: world.plan(), reading: { opening: 'One speaker, two lines.', roles: [] }, suggestions: [], frames: [], edits: world.edits(),
        messages: [{ role: 'user', text: 'Make it warmer', kind: 'say', seq: 1 }, { role: 'assistant', text: 'Two lines to hear.', kind: 'say', seq: 2 }, ...world.messages] })
    }
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) {
      return json({ jobs: [...world.adds].filter((a) => !a.turn).reverse().map((a) => world.job(a)), turn: null, lock: world.lock(),
        queue: world.queue.map((q, k) => ({ id: q.id, video_id: 'p1', kind: 'action', label: q.label, payload: { op: 'add' }, position: k + 1, created_by: 'local', status: 'queued' })), queue_paused: false })
    }
    if (url.includes('/plans/plan1/approve') && method === 'POST') {
      if (world.running()) {
        const lock = world.lock()!
        return json({ detail: { code: 'video_busy', message: `Busy with ${lock.action.toLowerCase()}. Queue this change, or Stop.`, holder: lock.holder, action: lock.action, started_by: 'You', lock, queue: [] } }, 409)
      }
      const body = JSON.parse(req.postData() ?? '{}') as { items?: string[] }
      const ks = (body.items ?? []).map((i) => Number(i.slice(1)) - 1)
      const a = world.start(ks, req.headers()['x-voltage-tab'] ?? null)
      return json({ approved: ks.map((k) => ({ item_id: `i${k + 1}`, edit_id: `e${k + 1}`, overridden: false, speaker: 'A', voice_profile_id: 'mock' })), skipped: [], export: null,
        render_job: world.job(a), plan: world.plan() })
    }
    // Addendum 3: a turn takes the video like an Add; a second one at the same moment is refused (the editor queues its words).
    if (url.endsWith('/videos/p1/turns') && method === 'POST') {
      const lock = world.lock()
      if (lock) {
        return json({ detail: { code: 'video_busy', message: 'Voltage is working on this video. Queue this change, or Stop.', holder: lock.holder, action: lock.action, started_by: 'You', lock, queue: [] } }, 409)
      }
      const body = JSON.parse(req.postData() ?? '{}') as { text: string }
      const a = world.start([], req.headers()['x-voltage-tab'] ?? null, RENDER_S, body.text)
      return json(world.turnJob(a), 202)
    }
    const turnJob = /\/api\/jobs\/(T\d+)$/.exec(url)
    if (turnJob) {
      const a = world.adds.find((x) => x.job === turnJob[1])
      return a ? json(world.turnJob(a)) : json({ detail: 'job not found' }, 404)
    }
    if (url.endsWith('/videos/p1/queue') && method === 'POST') {
      const body = JSON.parse(req.postData() ?? '{}') as { label: string; payload: { item_ids?: string[]; text?: string } }
      const item = { id: world.queue.length + 1, label: body.label, items: (body.payload.item_ids ?? []).map((i) => Number(i.slice(1)) - 1), goal: body.payload.text }
      world.queue.push(item)
      return json({ id: item.id, video_id: 'p1', kind: 'action', label: item.label, payload: body.payload, position: item.id, created_by: 'local', status: 'queued' }, 201)
    }
    if (url.endsWith('/videos/p1/stop') && method === 'POST') {
      const a = world.running()
      if (!a) return json({ stopped: false, cancelled: 0, spent_usd: 0, message: null, lock: null })
      const lock = world.lock()
      a.status = 'cancelled'
      for (const k of a.items) world.added.delete(k)                 // the edit set as it was before the click
      const message = 'Stopped. Nothing in your video changed. $0.00 spent is still charged.'
      world.messages.push({ role: 'assistant', text: message, kind: 'say', seq: 3 + world.messages.length })
      return json({ stopped: true, cancelled: 0, spent_usd: 0, message, lock })
    }
    if (url.includes('/plans/plan1')) return json(world.plan())
    if (url.includes('/renders/latest')) {
      const m = world.manifest()
      return json({ mode: 'final', current_hash: m.edit_hash, stale: false, in_progress: null,
        latest: { render_id: m.render_id, version: m.version, edit_set_hash: m.edit_hash, created_at: AT, mode: 'final', render: m.render, includes: m.includes, manifest: m } })
    }
    if (url.endsWith('/export') && method === 'POST') return json({ ...world.manifest(), request_id: (JSON.parse(req.postData() ?? '{}') as { request_id?: number }).request_id ?? null })
    if (url.includes('/messages')) {
      const after = Number(new URL(url).searchParams.get('after') ?? 0)
      return json(world.messages.filter((m) => m.seq > after))
    }
    if (url.endsWith('/arrangement')) return json(null, 404)
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0.1, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 1, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [{ voice_id: 'mock', name: 'Asha', description: '', gender: 'female', accent: null, age: null }] })
    if (url.includes('/suggestions')) return json({ suggestions: [] })
    return json({})
  })
}

const row = (page: Page, k: number) => page.getByRole('listitem', { name: new RegExp(`^Line at 0:0${Math.floor(LINES[k].start)}`) })

async function open(page: Page, world: World) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await serve(page, world)
  await page.goto('/#v/p1')
  await expect(row(page, 1).getByRole('button', { name: /^Add it/ })).toBeVisible()
}

test.describe('one edit at a time per video', () => {
  test('while an Add runs the strip names it, its row says Adding…, and another Add is not silently grey', async ({ page }) => {
    const world = new World()
    await open(page, world)
    await row(page, 0).getByRole('button', { name: /^Add it/ }).click()
    await expect(page.getByTestId('status-text')).toHaveText(/^Adding 'Fresh every morning'…/)
    await expect(row(page, 0).getByTestId('row-chip')).toHaveText('Adding…')
    const second = row(page, 1).getByRole('button', { name: /^Add it/ })
    await expect(second).toBeEnabled()
    await second.click()
    await expect(page.getByTestId('busy-text')).toHaveText(/^Busy with adding 'Fresh every morning'\./)
    await expect(page.getByTestId('busy-stop')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('busy-hint')).toHaveCount(0)
    await expect(page.getByTestId('status-text')).not.toHaveText(/Adding/, { timeout: 10_000 })
    await expect(row(page, 0).getByTestId('row-chip')).toHaveText(/In the video/)
  })

  test('another tab or member sees "is editing" and the editor read-only', async ({ page }) => {
    const world = new World()
    // Held until the test lets go (a loaded machine can take longer than a render to open the page).
    const theirs = world.start([0], 'someone-elses-tab', 3600)
    await open(page, world)
    await expect(page.getByTestId('status-text')).toHaveText(/^Another tab is editing · Adding 'Fresh every morning'…/)
    await expect(row(page, 1).getByRole('button', { name: /^Add it/ })).toBeDisabled()
    await expect(page.getByTestId('status-strip').getByTestId('stop')).toHaveCount(0)
    theirs.seconds = 0
    await expect(page.getByTestId('status-text')).not.toHaveText(/editing/, { timeout: 10_000 })
    await expect(row(page, 1).getByRole('button', { name: /^Add it/ })).toBeEnabled()
  })

  test('two quick Adds: the first runs, the second waits in Up next, both land in order', async ({ page }) => {
    const world = new World()
    await open(page, world)
    await row(page, 0).getByRole('button', { name: /^Add it/ }).click()
    await expect(page.getByTestId('status-text')).toHaveText(/^Adding 'Fresh every morning'…/)
    await expect(row(page, 0).getByTestId('row-chip')).toHaveText('Adding…')
    // While Working the chat button reads Queue.
    await expect(page.getByTestId('voltage-pane').getByRole('button', { name: 'Queue' })).toHaveText('Queue')
    // The other Add is not silently grey: pressed, it says what the video is busy with.
    const second = row(page, 1).getByRole('button', { name: /^Add it/ })
    await expect(second).toBeEnabled()
    await second.click()
    await expect(page.getByTestId('busy-text')).toHaveText(/^Busy with adding 'Fresh every morning'\./)
    await page.getByTestId('queue-this').click()
    await expect(page.getByTestId('toast')).toContainText('Queued: Add line 2')
    await expect(page.getByTestId('up-next-chip')).toHaveText([/Add line 2/])
    // The first lands; the second starts by itself; then both are in the video, in order.
    await expect(page.getByTestId('status-text')).toHaveText(/^Adding 'Doors open at seven'…/, { timeout: 10_000 })
    await expect(page.getByTestId('up-next')).toHaveCount(0)
    await expect(page.getByTestId('status-text')).not.toHaveText(/Adding/, { timeout: 10_000 })
    expect(world.adds.map((a) => [a.items, a.status])).toEqual([[[0], 'done'], [[1], 'done']])
    await expect(row(page, 0).getByTestId('row-chip')).toHaveText(/In the video/)
    await expect(row(page, 1).getByTestId('row-chip')).toHaveText(/In the video/)
  })

  test('Stop during an Add: the edit set is what it was before the click', async ({ page }) => {
    const world = new World()
    await open(page, world)
    await row(page, 0).getByRole('button', { name: /^Add it/ }).click()
    await expect(page.getByTestId('status-text')).toHaveText(/^Adding 'Fresh every morning'…/)
    await page.getByTestId('status-strip').getByTestId('stop').click()
    await expect(page.getByTestId('toast')).toContainText('Stopped. Nothing in your video changed. $0.00 spent is still charged.')
    expect(world.edits()).toEqual([])
    await expect(row(page, 0).getByRole('button', { name: /^Add it/ })).toBeVisible()
    await expect(page.getByTestId('status-text')).not.toHaveText(/Adding/)
  })

  test('two tabs send a change at the same moment: exactly one runs, the other waits in Up next (addendum 3)', async ({ browser }) => {
    const world = new World()
    const context = await browser.newContext()
    const [a, b] = [await context.newPage(), await context.newPage()]
    await open(a, world)
    await open(b, world)
    const send = async (page: Page, words: string) => {
      const box = page.getByRole('textbox', { name: /describe a change/i })
      await box.fill(words)
      return box
    }
    const [boxA, boxB] = [await send(a, 'Make line 1 warmer'), await send(b, 'Make line 2 brighter')]
    // The same moment: both Enters go out together; the server lets one in.
    await Promise.all([boxA.press('Enter'), boxB.press('Enter')])
    await expect.poll(() => world.adds.filter((x) => x.turn).length + world.queue.length).toBe(2)
    const ran = world.adds.filter((x) => x.turn)
    expect(ran).toHaveLength(1)
    expect(world.queue.map((q) => q.goal)).toEqual([ran[0].turn === 'Make line 1 warmer' ? 'Make line 2 brighter' : 'Make line 1 warmer'])
    // The tab that lost the race says its words wait; the one that won is Working.
    const loser = ran[0].turn === 'Make line 1 warmer' ? b : a
    await expect(loser.getByTestId('toast')).toContainText('Queued: ')
    await expect(loser.getByText(/Something went wrong/)).toHaveCount(0)
    // When the first lands, the queued one runs, alone.
    await expect.poll(() => world.adds.filter((x) => x.turn).length, { timeout: 15_000 }).toBe(2)
    expect(world.adds.filter((x) => x.status === 'running').length).toBeLessThanOrEqual(1)
    await context.close()
  })
})
