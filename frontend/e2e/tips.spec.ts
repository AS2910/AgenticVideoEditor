import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Run 5 item 3: the tip queue in a real browser (API mocked). A first-time tip in
 *  the editor shows in Voltage's pane, in the flow: its box never meets the
 *  transcript's or the player's, at desktop and phone widths, it is never laid
 *  over the page (no fixed or absolute place), and Got it puts it away for good.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const LINES = Array.from({ length: 8 }, (_, i) => ({ text: `Line ${i + 1}: a sentence for the transcript.`, start: i * 2, end: i * 2 + 1.6, speaker: 'A' }))
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 16, container: 'mp4' }
const PROJECT = {
  video_id: 'p1', project_id: null, project_name: null, filename: 'eight-lines.mp4', duration: 16, media: MEDIA, created_at: '2026-10-20T08:00:00Z',
  consent_granted_at: '2026-10-20T08:00:00Z', transcript: LINES.flatMap((l) => l.text.split(' ').slice(0, 3).map((w, k) => ({ text: w, start: l.start + k * 0.3, end: l.start + k * 0.3 + 0.25 }))),
  statements: LINES, speakers: [{ label: 'A', name: 'Host', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
  plan: null, reading: { opening: 'Eight lines.', roles: [] }, suggestions: [], frames: [], edits: [], messages: [],
}
const ARRANGED = {
  arrangement: { order: [], pins: {}, min_gap: null, end: null }, duration: 16, overrun: 0, ease_ok: false, min_gap_default: 0.15, can_undo: false,
  lines: LINES.map((l, i) => ({ key: `L${i}`, index: i + 1, text: l.text, speaker: 'A', orig_start: l.start, orig_end: l.end, length: 1.6, gap: i ? 0.4 : 0, start: l.start, end: l.end, pinned: false, pushed_after: null, moved: false, replaced_by: null })),
}

async function mockApi(page: Page, puts: string[]) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (route.request().method() === 'PUT' && url.endsWith('/me/onboarding')) puts.push(route.request().postData() ?? '')
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true })
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

type Rect = { left: number; top: number; right: number; bottom: number }
const meets = (a: Rect, b: Rect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

const SIZES: [string, number, number][] = [['desktop', 1440, 900], ['laptop', 1280, 720], ['phone', 390, 844]]

for (const [name, w, h] of SIZES) {
  test(`a tip never meets the transcript or the player (${name} ${w}x${h})`, async ({ page }) => {
    const puts: string[] = []
    await page.setViewportSize({ width: w, height: h })
    await mockApi(page, puts)
    await page.goto('/#v/p1')
    await expect(page.getByTestId('transcript-list')).toBeVisible()
    const tip = page.getByRole('status', { name: 'Tip: First video' })
    await expect(tip).toBeVisible()
    await expect(page.locator('[data-tip]')).toHaveCount(1)

    const m = await page.evaluate(() => {
      const r = (el: Element | null) => { const b = el!.getBoundingClientRect(); return { left: b.left, top: b.top, right: b.right, bottom: b.bottom } }
      const tipEl = document.querySelector('[data-tip]')!
      // Any ancestor laid over the page would let the tip cover what is under it.
      let floating = false
      for (let el: Element | null = tipEl; el && el !== document.body; el = el.parentElement) {
        const p = getComputedStyle(el).position
        if (p === 'fixed' || p === 'absolute') floating = true
      }
      return {
        tip: r(tipEl), transcript: r(document.querySelector('[data-testid=transcript-list]')), player: r(document.querySelector('section[aria-label="Monitor"]')),
        inPane: !!tipEl.closest('[data-tip-slot="pane"]'), floating,
      }
    })
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/tip-${name}.png`, fullPage: true })
    expect(m.inPane).toBe(true)
    expect(m.floating).toBe(false)
    expect(meets(m.tip, m.transcript)).toBe(false)
    expect(meets(m.tip, m.player)).toBe(false)

    // The page under it is still usable while it is up; Got it puts it away for good.
    await page.locator('[data-line-key="L0"]').first().hover()
    await tip.getByRole('button', { name: 'Got it' }).click()
    await expect(page.locator('[data-tip]')).toHaveCount(0)
    await expect.poll(() => puts.some((p) => p.includes('first-upload'))).toBe(true)
    // The session's count is kept for the next load.
    const saved = await page.evaluate(() => window.localStorage.getItem('voltage-tip-session'))
    expect(JSON.parse(saved!).shown).toEqual(['first-upload'])
  })
}
