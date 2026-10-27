import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** The editor shell (2026-10-20): exactly the window, each pane scrolling itself;
 *  the transcript rows in their own list under a pinned header. API mocked: 30 lines. */

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const LINES = Array.from({ length: 30 }, (_, i) => ({ text: `Line ${i + 1}: a sentence long enough to wrap on a narrow column of the transcript.`, start: i * 2, end: i * 2 + 1.6, speaker: 'A' }))
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 60, container: 'mp4' }
const PROJECT = {
  video_id: 'p1', project_id: null, project_name: null, filename: 'thirty-lines.mp4', duration: 60, media: MEDIA, created_at: '2026-10-20T08:00:00Z',
  consent_granted_at: '2026-10-20T08:00:00Z', transcript: LINES.flatMap((l) => l.text.split(' ').slice(0, 3).map((w, k) => ({ text: w, start: l.start + k * 0.3, end: l.start + k * 0.3 + 0.25 }))),
  statements: LINES, speakers: [{ label: 'A', name: 'Host', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
  plan: null, reading: { opening: 'Thirty lines.', roles: [] }, suggestions: [], frames: [],
  edits: [], messages: [{ role: 'user', text: 'Make it shorter', kind: 'say', seq: 1 }, { role: 'assistant', text: 'Line 12 is the longest; I can tighten it.', kind: 'say', seq: 2 }],
}
const ARRANGED = {
  arrangement: { order: [], pins: {}, min_gap: null, end: null }, duration: 60, overrun: 0, ease_ok: false, min_gap_default: 0.15, can_undo: false,
  lines: LINES.map((l, i) => ({ key: `L${i}`, index: i + 1, text: l.text, speaker: 'A', orig_start: l.start, orig_end: l.end, length: 1.6, gap: i ? 0.4 : 0, start: l.start, end: l.end, pinned: false, pushed_after: null, moved: false, replaced_by: null })),
}

async function mockApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/videos/p1')) return json(PROJECT)
    if (url.endsWith('/arrangement')) return json(ARRANGED)
    if (url.includes('/messages')) return json([])
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

const SIZES: [number, number][] = [[1440, 900], [1280, 720], [1920, 1080]]

async function openEditor(page: Page, w: number, h: number) {
  await page.setViewportSize({ width: w, height: h })
  await mockApi(page)
  await page.goto('/#v/p1')
  await expect(page.getByTestId('transcript-list')).toBeVisible()
  // Long runs of untouched lines fold to "+ N more lines"; open them all.
  for (let k = 0; k < 5; k++) {
    const fold = page.getByRole('button', { name: /more lines$/ }).first()
    if (!(await fold.count())) break
    await fold.click()
  }
  await page.waitForTimeout(100)
  const keys = await page.locator('[data-line-key]').count()
  if (keys !== 30) console.log('rows with keys', keys, await page.locator('[role=listitem]').count(), (await page.getByTestId('transcript-list').innerText()).slice(0, 300))
  await expect(page.locator('[data-line-key="L29"]')).toHaveCount(1)
}

async function checkShell(page: Page) {
  const m = await page.evaluate(() => {
    const de = document.documentElement
    const box = (el: Element | null) => (el ? el.getBoundingClientRect() : null)
    const head = box(document.querySelector('[data-testid=editor-header]'))!
    const composer = box(document.querySelector('[data-tour=composer]'))!
    const list = document.querySelector<HTMLElement>('[data-testid=transcript-list]')!
    const main = document.querySelector<HTMLElement>('main')!
    return { docH: de.scrollHeight, vh: innerHeight, headTop: head.top, headBottom: head.bottom, composerBottom: composer.bottom,
      listH: list.getBoundingClientRect().height, listScrolls: list.scrollHeight > list.clientHeight, mainH: main.clientHeight }
  })
  expect(m.docH).toBe(m.vh)                       // the page never scrolls
  expect(m.headTop).toBe(0)                       // the header is in view
  expect(m.composerBottom).toBeLessThanOrEqual(m.vh)
  expect(m.listH).toBeGreaterThanOrEqual(320)
  expect(m.listH).toBeLessThanOrEqual(m.mainH)
  expect(m.listScrolls).toBe(true)
  // Rows keep their own height in a list of fixed height: none overlaps the next.
  const overlaps = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('[data-testid=transcript-list] > *')].map((e) => e.getBoundingClientRect()).filter((r) => r.height > 0)
    return rows.slice(1).filter((r, i) => r.top < rows[i].bottom - 1).length
  })
  expect(overlaps).toBe(0)
}

test.describe('the editor shell', () => {
  for (const [w, h] of SIZES) {
    test(`fits the window at ${w}x${h}; the last row and the composer are reachable`, async ({ page }) => {
      await openEditor(page, w, h)
      await checkShell(page)
      // The last row: the column brings the list into view, the list scrolls to it.
      const list = page.getByTestId('transcript-list')
      await list.scrollIntoViewIfNeeded()
      await list.evaluate((el) => { el.scrollTop = el.scrollHeight })
      const last = page.locator('[data-line-key="L29"]')
      const [lb, rb] = await Promise.all([list.boundingBox(), last.boundingBox()])
      expect(rb!.y + rb!.height).toBeLessThanOrEqual(lb!.y + lb!.height + 1)
      expect(rb!.y).toBeGreaterThanOrEqual(lb!.y - 1)
      await expect(page.getByRole('textbox', { name: 'Describe a change' })).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(h)
    })
  }

  test('resizing between sizes keeps the shell and recomputes the list', async ({ page }) => {
    await openEditor(page, 1440, 900)
    const heights: number[] = []
    for (const [w, h] of [[1280, 720], [1920, 1080], [1440, 900]] as [number, number][]) {
      await page.setViewportSize({ width: w, height: h })
      await page.waitForTimeout(150)
      await checkShell(page)
      heights.push(await page.getByTestId('transcript-list').evaluate((el) => el.getBoundingClientRect().height))
    }
    expect(heights[1]).toBeGreaterThan(heights[0])          // a taller window, a taller list
  })

  test('the list scrolls while the player stays put; the column scrolls to the tracks', async ({ page }) => {
    await openEditor(page, 1440, 900)
    const player = page.getByRole('region', { name: 'Monitor' })
    const list = page.getByTestId('transcript-list')
    await list.hover()
    await page.waitForTimeout(100)
    const before = (await player.boundingBox())!.y
    await page.mouse.wheel(0, 1500)
    await page.waitForTimeout(200)
    expect(await list.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
    expect((await player.boundingBox())!.y).toBe(before)     // only the list moved
    // Tracks open: the inner height is measured again, and the column scrolls to show them.
    const h0 = await list.evaluate((el) => el.getBoundingClientRect().height)
    // Run 5 item 5: Tracks is under More controls.
    await page.getByRole('button', { name: /More controls/ }).click()
    await page.getByRole('button', { name: /^Tracks/ }).click()
    await page.locator('#tracks').scrollIntoViewIfNeeded()
    await expect(page.locator('#tracks')).toBeInViewport()
    expect(await list.evaluate((el) => el.getBoundingClientRect().height)).toBe(h0)
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(900)
  })

  test('keyboard focus scrolls only the list; "line 12" in the thread brings its row', async ({ page }) => {
    await openEditor(page, 1440, 900)
    const mainTop = () => page.locator('main').evaluate((el) => el.scrollTop)
    await page.locator('[data-line-key="L0"]').focus()
    const start = await mainTop()
    for (let k = 0; k < 20; k++) await page.keyboard.press('ArrowDown')
    await expect(page.locator('[data-line-key="L20"]')).toBeFocused()
    await expect(page.locator('[data-line-key="L20"]')).toBeInViewport()
    expect(await mainTop()).toBe(start)                      // the column did not move
    // Scrolling the list is not a move: no row starts a glide after the list scrolls and re-renders.
    const glides = await page.evaluate(async () => {
      const l = document.querySelector<HTMLElement>('[data-testid=transcript-list]')!
      l.scrollTop += 300
      window.dispatchEvent(new Event('resize'))
      await new Promise((r) => setTimeout(r, 50))
      return document.getAnimations().filter((a) => a.constructor.name === 'Animation' && (a.effect as KeyframeEffect | null)?.target?.closest('[data-testid=transcript-list]')).length
    })
    expect(glides).toBe(0)
    await page.getByRole('button', { name: 'Line 12', exact: true }).click()
    const row = page.locator('[data-line-key="L11"]')
    await expect(row).toBeInViewport()
    await expect(row).toHaveAttribute('data-flash', '')
  })

  test('on a phone the panes stack, the page scrolls and the header stays', async ({ page }) => {
    await openEditor(page, 390, 844)
    const list = page.getByTestId('transcript-list')
    expect(await list.evaluate((el) => el.style.height)).toBe('')                  // no inner scroll
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(844)
    await page.mouse.wheel(0, 2000)
    await page.waitForTimeout(200)
    expect(await page.evaluate(() => scrollY)).toBeGreaterThan(0)
    expect((await page.getByTestId('editor-header').boundingBox())!.y).toBe(0)     // sticky
  })
})

/** SHELL (golive): the editor header fits with the bell. A busy header (a long project name,
 *  Brief changed, a language version chip, a long file name, the bell on) at desktop sizes:
 *  nothing overflows sideways and Export, the bell and the account circle stay on screen. */
const BUSY = {
  ...PROJECT, project_id: 'f1', project_name: 'Diwali festive campaign for the western region',
  filename: 'bhaji-cam-ad-final-final-with-the-new-price-and-the-longer-ending.mp4',
  brief_changed: true, made_with_brief: 2, brief_version: 4,
  master_id: 'p0', master_filename: 'bhaji-cam-ad-master.mp4', language: 'hi', language_label: 'Hindi', out_of_sync: true,
}
const ALL_FLAGS = ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse', 'golive.g4']

for (const [w, h] of [[1280, 720], [1360, 860], [1440, 900], [1920, 1080]] as [number, number][]) {
  test(`the editor header fits with the bell at ${w}x${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h })
    await mockApi(page)
    await page.route('**/api/me/flags', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ flags: ALL_FLAGS }) }))
    await page.route('**/api/me/notifications/count', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ unread: 12 }) }))
    await page.route('**/api/videos/p1', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUSY) }))
    await page.route('**/api/projects/f1/rules', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rules: [], rules_version: 0 }) }))
    await page.route('**/api/videos/p1/comments', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ comments: [], open: 0 }) }))
    await page.goto('/#v/p1')
    const header = page.getByTestId('editor-header')
    await expect(header).toBeVisible()
    const bell = page.getByRole('button', { name: /^Notifications/ })
    await expect(bell).toBeVisible()
    await expect(page.getByTestId('brief-changed')).toBeVisible()
    if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/shell-header-${w}.png` })
    const m = await header.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, docW: document.documentElement.scrollWidth, vw: innerWidth }))
    expect(m.sw).toBeLessThanOrEqual(m.cw)          // no horizontal overflow in the header
    expect(m.docW).toBeLessThanOrEqual(m.vw)        // nor on the page
    for (const el of [page.getByRole('link', { name: 'Export' }), bell, page.getByRole('link', { name: 'Account' })]) {
      const b = (await el.boundingBox())!
      expect(b.x).toBeGreaterThanOrEqual(0)
      expect(b.x + b.width).toBeLessThanOrEqual(w)
      expect(b.y + b.height).toBeLessThanOrEqual(h)
    }
  })
}
