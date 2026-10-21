import { expect, test } from '@playwright/test'
import type { Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** G8 in a real browser (API mocked): thumbs on a take (down, with a reason) and on
 *  Voltage's reply (up, then Skip); a screen that throws shows the error card and reports
 *  to POST /errors. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const AT = '2026-10-20T10:00:00Z'
const FLAGS = { flags: ['projects.consistency', 'golive.g8'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-upload', 'first-question', 'first-proposal', 'first-thumbs'], checklist: [], checklist_hidden: true }
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4' }
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] }
const LINE = { text: 'Get thirty percent off today.', start: 0.2, end: 2.0, speaker: 'A' }
const TAKE = { candidate_id: 'c1', plan: { selection: { start: 0.2, end: 2.0 }, new_text: 'Now forty percent off today.', voice_profile_id: 'jeevan', mix: 'replace' },
  audio: { kind: 'audio', sha256: '1'.repeat(64), duration: 1.8, container: 'wav' }, frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 1.8, container: 'mp4' }, continuity: CONT, fit_notes: [] }
const ITEM = { item_id: 'i1', selection: { start: 0.2, end: 2.0 }, old_text: LINE.text, new_text: TAKE.plan.new_text, speaker: 'A', mix: 'replace', reason: 'The new offer.',
  kind: 'planned', enabled: true, status: 'ready', fit: null, candidate: TAKE, edit_id: null, question: null, error: null, note: null, progress: null }
const PLAN = { type: 'plan', plan_id: 'plan1', goal: 'The new offer', summary: '', mode: 'ask', status: 'done', created_at: AT, estimate: { items: 1, voice_characters: 30, usd: 0.01, seconds: 0 },
  findings: [], question: null, answers: [], log: [], spend_usd: 0.01, items: [ITEM] }
const VIDEO = {
  video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 2.3, media: MEDIA, created_at: AT, consent_granted_at: AT, stage: 'draft',
  brief_version: 1, made_with_brief: 1, brief_changed: false,
  transcript: LINE.text.split(' ').map((w, k, ws) => ({ text: w, start: LINE.start + (k * (LINE.end - LINE.start)) / ws.length, end: LINE.start + ((k + 0.9) * (LINE.end - LINE.start)) / ws.length })),
  statements: [LINE], speakers: [{ label: 'A', name: 'Jeevan', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
  plan: PLAN, reading: { opening: 'One speaker, one line.', roles: [] }, suggestions: [], frames: [], edits: [],
  messages: [{ role: 'user', text: 'Make it forty percent', kind: 'say', seq: 1 }, { role: 'assistant', text: 'One line, ready to hear.', kind: 'say', seq: 2 }],
}

test('G8: thumbs on a take and a reply, with an optional reason', async ({ page }) => {
  const puts: string[] = []
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json(FLAGS)
    if (url.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (url.endsWith('/videos/p1/feedback')) {
      if (method === 'PUT') { puts.push(req.postData() ?? ''); const b = JSON.parse(req.postData() ?? '{}'); return json({ ...b, reason: b.reason ?? '' }) }
      return json({ take: {}, turn: {} })
    }
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/videos/p1')) return json(VIDEO)
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) return json({ jobs: [], turn: null })
    if (url.includes('/plans/plan1')) return json(PLAN)
    if (url.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
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
  const take = page.getByTestId('thumbs-take').first()
  await expect(take).toBeVisible()
  await take.getByRole('button', { name: 'Not a good take', exact: true }).click()
  await expect(take.getByRole('button', { name: 'Not a good take', exact: true })).toHaveAttribute('aria-pressed', 'true')
  const why = take.getByRole('textbox', { name: 'What was off with this take? (optional)' })
  await why.fill('Too fast at the end')
  const buttons = take.locator('form').getByRole('button')
  await expect(buttons.last()).toHaveText('Send')                       // the next action last
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g8-take-reason.png` })
  await take.getByRole('button', { name: 'Send' }).click()
  await expect(take.getByRole('status')).toHaveText('Thanks. That helps.')

  const reply = page.getByTestId('thumbs-turn').first()
  await reply.getByRole('button', { name: 'Good reply', exact: true }).click()
  await expect(reply.getByRole('button', { name: 'Good reply', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await reply.getByRole('button', { name: 'Skip' }).click()
  await expect(reply.getByRole('textbox')).toHaveCount(0)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g8-reply.png` })
  expect(puts.map((p) => JSON.parse(p))).toEqual([
    { target: 'take', target_id: 'c1', vote: 'down', reason: '' },
    { target: 'take', target_id: 'c1', vote: 'down', reason: 'Too fast at the end' },
    { target: 'turn', target_id: 'm2', vote: 'up', reason: '' },
  ])
})

test('G8: an error nothing caught is reported to POST /errors', async ({ page }) => {
  const reports: { message: string; kind: string }[] = []
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path === '/api/errors') { reports.push(JSON.parse(req.postData() ?? '{}')); return route.fulfill({ status: 204, body: '' }) }
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/projects') return json({ projects: [] })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: [] })
    return json({})
  })
  await page.goto('/')
  await page.evaluate(() => { setTimeout(() => { throw new Error('Kaboom in a timer') }, 0) })
  await expect.poll(() => reports.some((r) => r.message.includes('Kaboom in a timer') && r.kind === 'error')).toBe(true)
})
