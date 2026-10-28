import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Run 5 addendum 3, item 3: messages queue clearly, in a real browser against a scripted server
 *  (no vendor, nothing spent). Two messages typed while Voltage is Working become "Queued 1 of 2"
 *  and "Queued 2 of 2" cards in the thread and chips in Up next; when the video is let go they run
 *  one at a time, in order: Running, then Done. The events channel answers 404, so the editor
 *  reads the lock and Up next through GET /jobs?active=1. */

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const RUN_S = 2
const AT = '2026-10-28T10:00:00Z'
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 30, container: 'mp4' }
const LINES = [{ text: 'Our bread is baked every day.', start: 1.0, end: 4.0, speaker: 'A' }]

interface Item { id: number; text: string; status: 'queued' | 'running' | 'done'; position: number }

/** The scripted server: one thing holds the video at a time; when it lets go the first waiting message starts. */
class World {
  items: Item[] = []
  /** What holds the video now: the turn that was running when the page opened, or a queued message. */
  holding: { item: number | null; until: number } | null = { item: null, until: Number.POSITIVE_INFINITY }
  messages: { role: string; text: string; kind: string; seq: number; data?: Record<string, unknown> }[] = []
  /** Every moment two things ran at once (must stay empty). */
  overlaps: number[] = []
  started: number[] = []
  say(role: string, text: string, data?: Record<string, unknown>) {
    this.messages.push({ role, text, kind: 'say', seq: 3 + this.messages.length, data })
  }
  tick() {
    if (this.holding && Date.now() >= this.holding.until) {
      const ran = this.items.find((i) => i.id === this.holding!.item)
      if (ran) { ran.status = 'done'; this.say('assistant', `Done: ${ran.text}`) }
      this.holding = null
    }
    if (!this.holding) {
      const next = this.items.find((i) => i.status === 'queued')
      if (next) {
        // Planned now, against the video as the one before left it.
        next.status = 'running'
        this.started.push(next.id)
        this.say('user', next.text, { queued: next.id })
        this.holding = { item: next.id, until: Date.now() + RUN_S * 1000 }
      }
    }
    if (this.items.filter((i) => i.status === 'running').length > 1) this.overlaps.push(Date.now())
  }
  letGo() { if (this.holding) this.holding.until = Date.now() }
  view(i: Item) { return { id: i.id, video_id: 'p1', kind: 'goal', label: i.text, payload: { text: i.text }, position: i.position, created_by: 'local', status: i.status, error: null } }
  live() { return this.items.filter((i) => i.status !== 'done').sort((a, b) => (a.status === 'running' ? -1 : b.status === 'running' ? 1 : a.position - b.position)).map((i) => this.view(i)) }
  recent() { return this.items.filter((i) => i.status === 'done').map((i) => this.view(i)) }
  lock() {
    if (!this.holding) return null
    return { video_id: 'p1', holder: 'turn:T1', action: 'Voltage is planning', started_by: 'local', started_by_name: 'You', tab: null,
      started_at: AT, stoppable: true, waiting: false, lease_expires_at: AT }
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
        plan: null, reading: { opening: 'One speaker, one line.', roles: [] }, suggestions: [], frames: [], edits: [],
        messages: [{ role: 'user', text: 'Make it warmer', kind: 'say', seq: 1 }, { role: 'assistant', text: 'On it.', kind: 'say', seq: 2 }, ...world.messages] })
    }
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) {
      return json({ jobs: [], turn: null, lock: world.lock(), queue: world.live(), queue_paused: false, queue_recent: world.recent() })
    }
    if (url.endsWith('/videos/p1/queue') && method === 'POST') {
      const body = JSON.parse(req.postData() ?? '{}') as { payload: { text: string } }
      const item: Item = { id: world.items.length + 1, text: body.payload.text, status: 'queued', position: world.items.length + 1 }
      world.items.push(item)
      return json(world.view(item), 201)
    }
    if (url.endsWith('/videos/p1/queue')) return json({ items: world.live(), paused: false, recent: world.recent() })
    if (url.includes('/messages')) {
      const after = Number(new URL(url).searchParams.get('after') ?? 0)
      return json(world.messages.filter((m) => m.seq > after))
    }
    if (url.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
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

test('two messages typed while Working: Queued 1 of 2 and 2 of 2, then Running and Done in order', async ({ page }) => {
  const world = new World()
  await page.setViewportSize({ width: 1440, height: 900 })
  await serve(page, world)
  await page.goto('/#v/p1')
  const pane = page.getByTestId('voltage-pane')
  // Working: the send button reads Queue.
  await expect(pane.getByRole('button', { name: 'Queue' })).toBeVisible()
  const box = pane.getByRole('textbox', { name: /describe a change/i })
  await box.fill('Make the opening line warmer and slower please')
  await box.press('Enter')
  await expect(pane.getByTestId('queued-card')).toHaveCount(1)
  await box.fill('Then make the ending shorter')
  await box.press('Enter')

  // Two cards in the thread, in order, and the same two in Up next.
  const cards = pane.getByTestId('queued-card')
  await expect(cards).toHaveCount(2)
  await expect(cards.nth(0)).toHaveAttribute('aria-label', 'Queued 1 of 2: Make the opening line warmer and...')
  await expect(cards.nth(1)).toHaveAttribute('aria-label', 'Queued 2 of 2: Then make the ending shorter')
  await expect(page.getByTestId('up-next-chip')).toHaveText(['Queued 1 of 2: Make the opening line warmer and...', 'Queued 2 of 2: Then make the ending shorter'])
  expect(world.started).toEqual([])
  // A reload keeps them: they are the server's, not the tab's.
  await page.reload()
  await expect(pane.getByTestId('queued-card')).toHaveCount(2)
  await expect(page.getByTestId('up-next-chip')).toHaveText(['Queued 1 of 2: Make the opening line warmer and...', 'Queued 2 of 2: Then make the ending shorter'])

  // The video is let go: the first runs alone, the second still waits.
  world.letGo()
  const turns = pane.getByTestId('queued-turn')
  await expect(turns).toHaveCount(1, { timeout: 10_000 })
  await expect(turns.nth(0)).toHaveAttribute('data-state', 'running')
  await expect(turns.nth(0).getByTestId('queued-state')).toHaveText('Running')
  await expect(cards).toHaveCount(1)
  await expect(cards.nth(0)).toHaveAttribute('aria-label', 'Queued 1 of 1: Then make the ending shorter')
  await expect(page.getByTestId('up-next-chip')).toHaveText(['Running: Make the opening line warmer and...', 'Queued 1 of 1: Then make the ending shorter'])

  // Then the second, only after the first is Done (the first folds into an earlier turn, keeping its state).
  const states = pane.getByTestId('queued-state')
  await expect(states).toHaveText(['Done', 'Running'], { timeout: 10_000 })
  await expect(turns.nth(0)).toContainText('Then make the ending shorter')
  await expect(states).toHaveText(['Done', 'Done'], { timeout: 10_000 })
  await expect(pane.getByTestId('queued-card')).toHaveCount(0)
  await expect(page.getByTestId('up-next')).toHaveCount(0)
  expect(world.started).toEqual([1, 2])
  expect(world.overlaps).toEqual([])
})
