import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** One edit at a time, part 5: the newest item is the bottom of the thread; the chips are one
 *  row inside the composer, offered only while the video is Ready. API mocked, a turn scripted. */

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const LINES = Array.from({ length: 6 }, (_, i) => ({ text: `Line ${i + 1}: a short sentence.`, start: i * 2, end: i * 2 + 1.6, speaker: 'A' }))
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 12, container: 'mp4' }
const chip = (label: string, kind: string) => ({ label, prompt: `${label}, please.`, kind, grounded_in: 'time' })
const CHIPS = [chip('Make line 1 warmer', 'voice'), chip('Tighten line 2', 'fix'), chip('Export the video', 'finish'), chip('Add an offer at the end', 'add')]
const PLAN = {
  plan_id: 'pl1', goal: 'Make it warmer', summary: '', mode: 'ask', status: 'done', created_at: '2026-10-25T08:00:00Z',
  estimate: { items: 0, voice_characters: 0, usd: 0, seconds: 0 }, findings: [], question: null, spend_usd: 0, log: [], items: [],
}
const QUESTION = { text: 'Which voice for line 2?', options: ['Warm', 'Bright'], guess: 'Warm' }
// Enough said before that the thread scrolls (earlier turns fold, so the latest answer is long).
const EARLIER = Array.from({ length: 12 }, (_, i) => [
  { role: 'user', text: `Ask ${i + 1}`, kind: 'say', seq: i * 2 + 1 },
  { role: 'assistant', text: `Answer ${i + 1}. ${'A longer reply that takes a few lines in the pane. '.repeat(i === 11 ? 40 : 3)}`, kind: 'say', seq: i * 2 + 2 },
]).flat()

interface World { messages: object[]; suggestions: object[]; plan: object | null; jobs: object[]; turnDone: boolean; turnResult: object }

async function mockApi(page: Page, world: World) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/videos/p1')) return json({
      video_id: 'p1', project_id: null, project_name: null, filename: 'six-lines.mp4', duration: 12, media: MEDIA, created_at: '2026-10-25T08:00:00Z',
      consent_granted_at: '2026-10-25T08:00:00Z', transcript: [], statements: LINES, speakers: [{ label: 'A', name: 'Host', voice_id: null }],
      settings: { autonomy: 'ask', turn_usd: 0.5 }, plan: world.plan, reading: { opening: 'Six lines.', roles: [] }, suggestions: world.suggestions,
      frames: [], edits: [], messages: world.messages.filter((m) => (m as { seq: number }).seq <= EARLIER.length),
    })
    if (url.endsWith('/videos/p1/turns') && method === 'POST') return json({ job_id: 't1', kind: 'turn', project_id: 'p1', status: 'running', progress: 0, step: 'Thinking…', attempts: 0, result: null, error: null })
    if (url.endsWith('/jobs/t1')) return json(world.turnDone
      ? { job_id: 't1', kind: 'turn', project_id: 'p1', status: 'succeeded', progress: 1, step: 'Done', attempts: 1, result: world.turnResult, error: null }
      : { job_id: 't1', kind: 'turn', project_id: 'p1', status: 'running', progress: 0.4, step: 'Voicing line 1', attempts: 1, result: null, error: null })
    if (url.includes('/messages')) {
      const after = Number(new URL(url).searchParams.get('after') ?? 0)
      return json(world.messages.filter((m) => (m as { seq: number }).seq > after))
    }
    if (url.includes('/videos/p1/jobs')) return json({ jobs: world.jobs, turn: null })
    if (url.endsWith('/arrangement')) return json({ arrangement: { order: [], pins: {}, min_gap: null, end: null }, duration: 12, overrun: 0, ease_ok: false, min_gap_default: 0.15, can_undo: false, lines: [] })
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/renders')) return json({ final: { render: null, rendering: false, edits: 0 }, proposals: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [] })
    return json({})
  })
}

const world = (more: Partial<World> = {}): World => ({
  messages: [...EARLIER], suggestions: CHIPS, plan: null, jobs: [], turnDone: false, turnResult: { type: 'turn', plan: PLAN, suggestions: CHIPS }, ...more,
})

async function open(page: Page, w: World) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockApi(page, w)
  await page.goto('/#v/p1')
  await expect(page.getByRole('textbox', { name: 'Describe a change' })).toBeVisible()
}

const chips = (page: Page) => page.getByRole('group', { name: 'Suggestions for this video' })
const labels = async (page: Page) => new Set(await chips(page).getByRole('button').allTextContents())
const box = (page: Page) => page.getByRole('textbox', { name: 'Describe a change' })
const thread = (page: Page) => page.getByRole('log', { name: 'The conversation' })

/** The turn answers with Voltage's reply (and the plan it ends with). */
function finish(w: World, reply: string, more: Partial<World> = {}) {
  w.messages = [...w.messages, { role: 'assistant', text: reply, kind: 'say', seq: w.messages.length + 2 }]
  Object.assign(w, more, { turnDone: true })
}

test.describe('chat order and chips', () => {
  test('three chips in one row inside the composer; a new reply is the last thing in the thread', async ({ page }) => {
    const w = world()
    await open(page, w)
    await expect(chips(page).getByRole('button')).toHaveCount(3)
    // Inside the composer box, above the words, all on one line.
    const composer = page.locator('[data-tour=composer]')
    await expect(composer.getByRole('group', { name: 'Suggestions for this video' })).toBeVisible()
    const [row, words] = await Promise.all([page.getByTestId('chip-row').boundingBox(), box(page).boundingBox()])
    expect(row!.y + row!.height).toBeLessThanOrEqual(words!.y + 1)
    const ys = await chips(page).getByRole('button').evaluateAll((bs) => bs.map((b) => Math.round(b.getBoundingClientRect().top)))
    expect(new Set(ys).size).toBe(1)
    expect(row!.height).toBeLessThanOrEqual(36)
    // A turn: while it runs the chips are gone; its reply ends the thread; the chips are back in the box, a different set.
    const before = await labels(page)
    await box(page).fill('Make it warmer')
    await expect(chips(page)).toHaveCount(0)                    // typing
    await box(page).press('Enter')
    await expect(page.getByTestId('turn-working')).toBeVisible()
    await expect(chips(page)).toHaveCount(0)                    // the turn runs
    finish(w, 'Line 1 is warmer now. Hear it on its row.')
    await expect(thread(page).getByText('Line 1 is warmer now.')).toBeVisible()
    await expect(page.getByTestId('turn-working')).toHaveCount(0)
    const last = await thread(page).evaluate((el) => el.lastElementChild?.textContent ?? '')
    expect(last).toContain('Line 1 is warmer now.')
    await expect(chips(page).getByRole('button')).toHaveCount(3)
    const after = await labels(page)
    expect([...after].sort()).not.toEqual([...before].sort())  // never the same set twice in a row
    // Never saved into the thread.
    for (const c of CHIPS) await expect(thread(page)).not.toContainText(c.label)
  })

  test('a question waiting hides the chips; the card is the last thing in the thread', async ({ page }) => {
    const w = world()
    await open(page, w)
    await box(page).fill('Change line 2')
    await box(page).press('Enter')
    finish(w, 'I can voice line 2 two ways.', { plan: { ...PLAN, status: 'clarifying', question: QUESTION }, turnResult: { type: 'turn', plan: { ...PLAN, status: 'clarifying', question: QUESTION }, suggestions: CHIPS } })
    await expect(page.getByTestId('clarify')).toBeVisible()
    expect(await thread(page).evaluate((el) => el.lastElementChild?.getAttribute('data-testid'))).toBe('clarify')
    await expect(chips(page)).toHaveCount(0)
  })

  test('a job running on the video hides the chips', async ({ page }) => {
    const job = { job_id: 'r1', video_id: 'p1', turn_id: null, kind: 'render_preview', status: 'running', step_label: 'Rendering', progress: 0.3, line_ids: [], created_at: '2026-10-25T08:00:00Z', started_at: '2026-10-25T08:00:00Z', finished_at: null, eta_s: 5, error_code: null, error_text: null, cost_usd: null }
    const w = world({ jobs: [job] })
    await open(page, w)
    await page.waitForTimeout(500)
    await expect(chips(page)).toHaveCount(0)
    w.jobs = [{ ...job, status: 'done', progress: 1, finished_at: '2026-10-25T08:00:05Z', eta_s: null }]
    await expect(chips(page).getByRole('button')).toHaveCount(3, { timeout: 15_000 })   // the poll reads it done
  })

  test('the x hides the chips until the next finished turn', async ({ page }) => {
    const w = world()
    await open(page, w)
    await page.getByRole('button', { name: 'Hide suggestions' }).click()
    await expect(chips(page)).toHaveCount(0)
    await box(page).fill('Tighten line 2')
    await box(page).press('Enter')
    finish(w, 'Line 2 is tighter.')
    await expect(thread(page).getByText('Line 2 is tighter.')).toBeVisible()
    await expect(chips(page).getByRole('button')).toHaveCount(3)
  })

  test('scrolled up, a new reply brings the pill instead of a jump', async ({ page }) => {
    const w = world()
    await open(page, w)
    const log = thread(page)
    await box(page).fill('Make it shorter')
    await box(page).press('Enter')
    await expect(page.getByTestId('turn-working')).toBeVisible()
    // While it works, Voltage says a long piece (the thread scrolls); you scroll up to read it.
    w.messages = [...w.messages, { role: 'assistant', text: `Reading it through. ${'A sentence on what the video says now. '.repeat(40)}`, kind: 'say', seq: w.messages.length + 2 }]
    await expect(log.getByText('Reading it through.')).toBeVisible()
    await expect.poll(() => log.evaluate((el) => el.scrollHeight > el.clientHeight + 200)).toBe(true)
    await log.evaluate((el) => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')) })
    finish(w, 'Shorter now, by two seconds.')
    const pill = page.getByTestId('new-from-voltage')
    await expect(pill).toHaveText('New from Voltage ↓')
    expect(await log.evaluate((el) => el.scrollTop)).toBe(0)
    await pill.click()
    await expect(pill).toHaveCount(0)
    await expect(log.getByText('Shorter now, by two seconds.')).toBeInViewport()
  })
})
