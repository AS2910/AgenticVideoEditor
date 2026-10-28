import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Run 5 addendum 3, item 5: Pause and Stop, in a real browser against a scripted server (no vendor,
 *  nothing spent). A turn voices two lines, one step each. Pause pressed mid step: that step finishes,
 *  the strip reads "Paused after voicing line 1" with Resume and Stop, and nothing new starts. Resume
 *  carries on with line 2 only; Stop leaves the video as it was. Both say what was spent and that it
 *  is still charged. The events channel answers 404, so the editor reads the turn through GET /jobs. */

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const STEP_S = 1.5
const AT = '2026-10-28T10:00:00Z'
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 30, container: 'mp4' }
const LINES = [
  { text: 'Our bread is baked every day.', start: 1.0, end: 4.0, speaker: 'A' },
  { text: 'Come in before nine.', start: 6.0, end: 9.0, speaker: 'A' },
]
const PAUSED = 'Paused. $0.06 spent so far is still charged. Resume to finish.'
const STOPPED = 'Stopped. Nothing in your video changed. $0.06 spent is still charged.'

/** The scripted server: a turn voicing line 1 then line 2, a step each; Pause holds it between them. */
class World {
  state: 'running' | 'paused' | 'done' | 'stopped' = 'running'
  pausing = false
  step = 1
  stepAt = Date.now()
  /** Every line voiced, in order (a line voiced twice would show here twice). */
  voiced: number[] = []
  messages: { role: string; text: string; kind: string; seq: number }[] = []
  say(text: string) { this.messages.push({ role: 'assistant', text, kind: 'say', seq: 3 + this.messages.length }) }
  spent() { return 0.06 * Math.max(1, this.voiced.length) }
  /** Line 1's take is the vendor call in flight when the page opens: it finishes STEP_S after Pause is
   *  pressed (never on its own, so a slow machine cannot finish it before the click). */
  pausedAt: number | null = null
  tick() {
    if (this.state !== 'running') return
    const from = this.step === 1 ? this.pausedAt : this.stepAt
    if (from === null || Date.now() - from < STEP_S * 1000) return
    this.voiced.push(this.step)
    if (this.pausing) {
      // The step running when Pause was pressed finished; the turn holds before the next one.
      this.pausing = false
      this.state = 'paused'
      this.say(PAUSED)
      return
    }
    if (this.step === LINES.length) { this.state = 'done'; this.say('Both lines are ready to hear.'); return }
    this.step += 1
    this.stepAt = Date.now()
  }
  turn() {
    const step = this.state === 'paused' ? `Paused after voicing line ${this.step}` : this.state === 'running' ? `Voicing line ${this.step}`
      : this.state === 'stopped' ? 'Stopped' : 'Done'
    const over = this.state === 'done' || this.state === 'stopped'
    return { turn_id: 'T1', status: over ? 'done' : this.state, step, started_at: AT, finished_at: over ? new Date().toISOString() : null,
      spent_usd: this.spent(), pausing: this.pausing, message: this.state === 'paused' ? PAUSED : null, lines_voiced: this.voiced.length }
  }
  lock() {
    if (this.state === 'done' || this.state === 'stopped') return null
    const paused = this.state === 'paused'
    return { video_id: 'p1', holder: paused ? 'pause:T1' : 'turn:T1', action: paused ? `Paused after voicing line ${this.step}` : `Voicing line ${this.step}`,
      started_by: 'local', started_by_name: 'You', tab: null, started_at: AT, stoppable: true, waiting: false, lease_expires_at: AT,
      paused, spent_usd: this.spent() }
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
        plan: null, reading: { opening: 'One speaker, two lines.', roles: [] }, suggestions: [], frames: [], edits: [],
        messages: [{ role: 'user', text: 'Make both lines warmer', kind: 'say', seq: 1 }, { role: 'assistant', text: 'On it.', kind: 'say', seq: 2 }, ...world.messages] })
    }
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) {
      return json({ jobs: [], turn: world.turn(), lock: world.lock(), queue: [], queue_paused: false, queue_recent: [] })
    }
    if (url.endsWith('/videos/p1/pause') && method === 'POST') {
      world.pausing = true
      world.pausedAt = Date.now()
      return json({ pausing: true, paused: false, spent_usd: world.spent(), lock: world.lock() })
    }
    if (url.endsWith('/videos/p1/resume') && method === 'POST') {
      // From the next step: the line already voiced is not voiced again.
      world.state = 'running'
      world.step += 1
      world.stepAt = Date.now()
      return json({ resumed: true, lock: world.lock() })
    }
    if (url.endsWith('/videos/p1/stop') && method === 'POST') {
      const held = world.lock()
      world.state = 'stopped'
      world.say(STOPPED)
      return json({ stopped: true, cancelled: 0, spent_usd: world.spent(), message: STOPPED, lock: held })
    }
    if (url.endsWith('/videos/p1/queue')) return json({ items: [], paused: false, recent: [] })
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

async function pausedMidStep(page: Page, world: World) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await serve(page, world)
  await page.goto('/#v/p1')
  const strip = page.getByTestId('status-strip')
  // Before either is pressed, both say what has been spent.
  await expect(strip.getByTestId('spent-so-far')).toHaveText('Spent so far: $0.06')
  await expect(strip.getByTestId('pause')).toBeVisible()
  await expect(strip.getByTestId('stop')).toBeVisible()
  await expect(strip.getByTestId('pause')).toHaveAccessibleDescription('Spent so far: $0.06')
  await strip.getByTestId('pause').click()
  // The step running now finishes, then it holds: Resume and Stop, and nothing new starts.
  await expect(page.getByTestId('status-text')).toHaveText('Paused after voicing line 1', { timeout: 10_000 })
  await expect(page.getByText(PAUSED).first()).toBeVisible()
  await expect(strip.getByTestId('resume')).toBeVisible()
  await expect(strip.getByTestId('stop')).toBeVisible()
  await expect(strip.getByTestId('pause')).toHaveCount(0)
  await expect(strip.getByTestId('spent-so-far')).toHaveText('Spent so far: $0.06')
  await page.waitForTimeout(STEP_S * 1000 + 500)
  expect(world.voiced).toEqual([1])
  return strip
}

test('pause then resume: the step running finishes, then it holds; Resume voices only the next line', async ({ page }) => {
  const world = new World()
  const strip = await pausedMidStep(page, world)
  await strip.getByTestId('resume').click()
  await expect(page.getByTestId('status-text')).toHaveText('Voicing line 2', { timeout: 10_000 })
  await expect(strip.getByTestId('pause')).toBeVisible()
  await expect(page.getByTestId('status-text')).toHaveText('Up to date', { timeout: 15_000 })
  expect(world.voiced).toEqual([1, 2])               // nothing voiced twice
})

test('pause then stop: Stop says nothing changed and what was spent is still charged', async ({ page }) => {
  const world = new World()
  const strip = await pausedMidStep(page, world)
  await strip.getByTestId('stop').click()
  await expect(page.getByTestId('toast')).toContainText(STOPPED)
  await expect(page.getByTestId('status-text')).toHaveText('Up to date', { timeout: 10_000 })
  await expect(strip.getByTestId('resume')).toHaveCount(0)
  expect(world.voiced).toEqual([1])
})

test('at phone width the strip keeps the spend, Pause and Stop inside the screen', async ({ page }) => {
  const world = new World()
  await page.setViewportSize({ width: 375, height: 800 })
  await serve(page, world)
  await page.goto('/#v/p1')
  const strip = page.getByTestId('status-strip')
  await expect(strip.getByTestId('spent-so-far')).toBeVisible()
  await expect(strip.getByTestId('pause')).toBeVisible()
  await expect(strip.getByTestId('stop')).toBeVisible()
  const box = await strip.boundingBox()
  expect(box!.width).toBeLessThanOrEqual(375)
  for (const id of ['spent-so-far', 'pause', 'stop']) {
    const b = await strip.getByTestId(id).boundingBox()
    expect(b!.x + b!.width).toBeLessThanOrEqual(375)
  }
})
