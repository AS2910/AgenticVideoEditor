import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Run 5 item 5, less to read: a new user's editor is the simple view (the player, the
 *  transcript, Voltage), with one Hear changes switch, labels in sentence case, and mono
 *  only for times and money. The Get started pill sits in the status strip, over nothing.
 *  API mocked: 8 lines, one added line in the video, one proposal waiting. SHOTS=dir saves screenshots. */

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const LINES = Array.from({ length: 8 }, (_, i) => ({ text: `Line ${i + 1}: the storyteller says something worth hearing here.`, start: i * 3, end: i * 3 + 2.4, speaker: 'A' }))
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 24, container: 'mp4' }
const TAKE = {
  candidate_id: 'c1', plan: { selection: { start: 3, end: 5.4 }, new_text: 'Line 2: the storyteller says something new.', voice_profile_id: 'v1', mix: 'replace' },
  audio: { kind: 'audio', sha256: 'a'.repeat(64), duration: 2.3, container: 'wav' }, frames: null,
  continuity: { voice_match: null, prosody: 0.95, audio_integration: 0.98, lip_sync: null, passed: true, warnings: [], measured: [] },
}
const PLAN = {
  type: 'plan', plan_id: 'pl1', goal: 'x', summary: '', mode: 'ask', status: 'done', created_at: '2026-10-27T08:00:00Z', estimate: null, findings: [], question: null, spend_usd: 0.04, log: [],
  items: [{ item_id: 'i1', selection: { start: 3, end: 5.4 }, old_text: LINES[1].text, new_text: TAKE.plan.new_text, speaker: 'A', mix: 'replace', reason: '', kind: 'planned', enabled: true,
    status: 'ready', fit: null, candidate: TAKE, edit_id: null, question: null, error: null, note: null, progress: null }],
}
const PROJECT = {
  video_id: 'p1', project_id: null, project_name: null, filename: 'the-owl-and-the-moon.mp4', duration: 24, media: MEDIA, created_at: '2026-10-27T08:00:00Z',
  consent_granted_at: '2026-10-27T08:00:00Z', transcript: LINES.flatMap((l) => l.text.split(' ').slice(0, 3).map((w, k) => ({ text: w, start: l.start + k * 0.3, end: l.start + k * 0.3 + 0.25 }))),
  statements: LINES, speakers: [{ label: 'A', name: 'Storyteller (the owl)', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5, ask_over_usd: 0.25 },
  plan: PLAN, reading: { opening: 'One storyteller, eight lines.', roles: [] }, suggestions: [{ kind: 'edit', label: 'Make line 3 warmer', prompt: 'Make line 3 warmer' }], frames: [],
  edits: [], messages: [
    { role: 'user', text: 'Change line 2', kind: 'say', seq: 1 },
    { role: 'assistant', text: 'Looked at line 2', kind: 'step', seq: 2, cost: 0, data: { tool: 'read_transcript', t: 1.1 } },
    { role: 'assistant', text: 'Voiced line 2', kind: 'step', seq: 3, cost: 0.04, data: { tool: 'synthesize_take', t: 6.2 } },
    { role: 'assistant', text: 'Line 2 is ready to hear. Add it if it sounds right.', kind: 'say', seq: 4, data: { why: 'I kept the storyteller voice and pace.\n0:03 to 0:05 · one line · $0.04' } },
  ],
}
const ARRANGED = {
  arrangement: { order: [], pins: {}, min_gap: null, end: null }, duration: 24, overrun: 0, ease_ok: false, min_gap_default: 0.15, can_undo: false,
  lines: LINES.map((l, i) => ({ key: `L${i}`, index: i + 1, text: l.text, speaker: 'A', orig_start: l.start, orig_end: l.end, length: 2.4, gap: i ? 0.6 : 0, start: l.start, end: l.end, pinned: false, pushed_after: null, moved: false, replaced_by: null })),
}

async function mockApi(page: Page, saved: unknown[] = []) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: ['goal'], checklist_hidden: false })
    if (url.endsWith('/me/settings') && route.request().method() === 'PUT') { saved.push(route.request().postDataJSON()); return json({ more_controls: true }) }
    if (url.endsWith('/videos/p1')) return json(PROJECT)
    if (url.endsWith('/arrangement')) return json(ARRANGED)
    if (url.includes('/messages')) return json([])
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/renders')) return json({ final: { render: null, rendering: false, edits: 0 }, proposals: null })
    if (url.includes('/usage')) return json({ spent_usd: 0.34, ceiling_usd: 10, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0.34, ceiling_usd: 10, label: 'This video' }, month: { spent_usd: 0.34, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [] })
    return json({})
  })
}

async function openEditor(page: Page, w: number, h: number, saved: unknown[] = []) {
  await page.setViewportSize({ width: w, height: h })
  await mockApi(page, saved)
  await page.goto('/#v/p1')
  await expect(page.getByTestId('transcript-list')).toBeVisible()
  await expect(page.getByRole('switch', { name: 'Hear changes' })).toBeVisible()
}

/** Visible text set in capitals by CSS, and mono text that is more than a time or an amount. */
async function typeAudit(page: Page) {
  return page.evaluate(() => {
    const roots = ['[data-testid=editor-header]', '[data-testid=status-strip]', 'main', '[data-testid=voltage-pane]'].map((q) => document.querySelector(q)).filter(Boolean) as Element[]
    const capitals: string[] = []
    const mono: string[] = []
    // A time, an amount, a count or a step's cost: digits and their marks, and "of", "free" and "s" between them.
    const timeOrMoney = (t: string) => t.replace(/\b(of|free|s|ms)\b/g, '').replace(/[\d$.,:%+\-−–~≈×·/\s]/g, '') === ''
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = (n.textContent ?? '').trim()
        const el = n.parentElement
        if (!text || !el || !/[A-Za-z]/.test(text)) continue
        const r = el.getBoundingClientRect()
        if (r.width === 0 || r.height === 0 || el.closest('.sr-only,[aria-hidden=true],kbd,.kbd,code,pre')) continue
        const cs = getComputedStyle(el)
        if (cs.textTransform === 'uppercase') capitals.push(text)
        if (/JetBrains Mono/i.test(cs.fontFamily) && !timeOrMoney(text)) mono.push(text)
      }
    }
    return { capitals, mono }
  })
}

const box = (r: { x: number; y: number; width: number; height: number }) => ({ l: r.x, t: r.y, r: r.x + r.width, b: r.y + r.height })
const meets = (a: ReturnType<typeof box>, b: ReturnType<typeof box>) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b

for (const [w, h] of [[1440, 900], [1280, 720], [390, 844]] as [number, number][]) {
  test(`the simple view at ${w}x${h}: one switch, no capitals, mono only for times and money, nothing over the transcript`, async ({ page }) => {
    await openEditor(page, w, h)
    // Simple: no three-way switch, no Tracks, no counts, no timing bar, no Bed, Effect or Fine-tune.
    await expect(page.getByRole('group', { name: 'Play' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Tracks/ })).toHaveCount(0)
    await expect(page.getByTestId('counts')).toHaveCount(0)
    await expect(page.getByTestId('arrange-bar')).toHaveCount(0)
    await expect(page.getByText('Fine-tune')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /More controls/ })).toBeVisible()
    // Voltage's words: two sentences, the rest behind Why?.
    const pane = page.getByTestId('voltage-pane')
    await expect(pane.getByText('Line 2 is ready to hear. Add it if it sounds right.')).toBeVisible()
    await expect(pane.getByText(/storyteller voice and pace/)).toHaveCount(0)
    await expect(pane.getByRole('button', { name: 'Why?' })).toBeVisible()

    const audit = await typeAudit(page)
    expect(audit.capitals).toEqual([])
    expect(audit.mono).toEqual([])

    // The header and the page never scroll sideways.
    const m = await page.getByTestId('editor-header').evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, docW: document.documentElement.scrollWidth, vw: innerWidth }))
    expect(m.sw).toBeLessThanOrEqual(m.cw)
    expect(m.docW).toBeLessThanOrEqual(m.vw)

    // The Get started pill: in the status strip, never fixed over the transcript.
    const pill = page.getByRole('button', { name: /^Get started/ })
    await expect(pill).toBeVisible()
    expect(await pill.evaluate((el) => getComputedStyle(el.closest('[data-testid=checklist]')!).position)).not.toBe('fixed')
    const list = page.getByTestId('transcript-list')
    for (const scroll of [0, 600, 1400]) {
      await page.evaluate((y) => window.scrollTo(0, y), scroll)
      await page.waitForTimeout(100)
      const [p, l] = await Promise.all([pill.boundingBox(), list.boundingBox()])
      if (p && l) expect(meets(box(p), box(l))).toBe(false)
    }
    await page.evaluate(() => window.scrollTo(0, 0))
    if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/simple-${w}x${h}.png`, fullPage: w < 960 })
  })
}

test('More controls brings the three ways to play, Tracks and the counts, and is kept for the user', async ({ page }) => {
  const saved: unknown[] = []
  await openEditor(page, 1440, 900, saved)
  await page.getByRole('button', { name: /More controls/ }).click()
  await expect(page.getByRole('group', { name: 'Play' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Tracks/ })).toBeVisible()
  await expect(page.getByTestId('counts')).toBeVisible()
  expect(saved).toEqual([{ more_controls: true }])
  const audit = await typeAudit(page)
  expect(audit.capitals).toEqual([])
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/more-controls-1440x900.png` })
})
