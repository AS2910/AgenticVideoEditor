import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** D2 in a real browser (API mocked, nothing spent): on the project page,
 *  Voltage's one suggestion from the last 10 decisions applies only on Add,
 *  then sits under What Voltage has learned until Remove takes it out; in the
 *  editor, Discard asks an optional why and sends the picked reason.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const AT = '2026-10-20T10:00:00Z'
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-learned', 'first-board', 'first-word-rule'], checklist: [], checklist_hidden: true }

const LEARNED = (extra: Record<string, unknown> = {}) => ({ item_id: 7, project_id: 'f1', kind: 'rule', text: 'Keep lines under eight words.', why: 'You shortened 4 of the last 10 lines before adding them.',
  status: 'suggested', rule_id: null, brief_version: null, at_count: 10, created_at: AT, decided_at: null, decided_by: null, ...extra })
const PROJECT = { project_id: 'f1', name: 'Diwali 2026', brief: 'Warm and bright.', settings: { autonomy: 'ask' }, ceiling_usd: null, spent_usd: 0.02, created_at: AT, video_count: 0, brief_version: 2 }

async function serveProject(page: Page, calls: string[]) {
  let state: Record<string, unknown> = { pending: LEARNED(), learned: [], decisions: 10, every: 10, reasons: ['Wrong words', 'Wrong voice', 'Too long', 'Not needed'] }
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') calls.push(`${method} ${path}`)
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/pins') return json({ pins: [] })
    if (path === '/api/projects/f1/learned') return json(state)
    if (path === '/api/projects/f1/learned/7/accept') {
      state = { ...state, pending: null, learned: [LEARNED({ status: 'accepted', rule_id: 3 })], project: PROJECT }
      return json(state)
    }
    if (path === '/api/projects/f1/learned/7' && method === 'DELETE') { state = { ...state, learned: [], project: PROJECT }; return json(state) }
    if (path === '/api/projects/f1') return json({ project: PROJECT, videos: [], voices: [], files: [], suggestions: [] })
    if (path === '/api/projects') return json({ projects: [PROJECT] })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    if (path.endsWith('/rules')) return json({ rules: [], rules_version: 0 })
    if (path.endsWith('/export-presets')) return json({ presets: [], codecs: ['h264'] })
    if (path.endsWith('/events')) return json({ events: [], next: null })
    if (/\/videos$/.test(path)) return json({ videos: [] })
    return json({})
  })
}

test('learned style: a suggestion applies only on Add, and Remove takes it back out', async ({ page }) => {
  const calls: string[] = []
  await page.setViewportSize({ width: 1280, height: 1000 })
  await serveProject(page, calls)
  await page.goto('/#p/f1')
  const card = page.getByTestId('learned')
  const suggestion = card.getByTestId('learned-suggestion')
  await expect(suggestion).toContainText('Keep lines under eight words.')
  await expect(suggestion).toContainText('You shortened 4 of the last 10 lines before adding them. Nothing changes until you add it.')
  await expect(card.getByTestId('learned-empty')).toBeVisible()
  expect(calls).toEqual([])                                      // nothing applied by showing it
  if (SHOTS) { await page.waitForTimeout(800); await page.screenshot({ path: `${SHOTS}/d2-suggestion.png`, fullPage: true }) }
  await suggestion.getByRole('button', { name: 'Add as a rule' }).click()
  await expect(card.getByTestId('learned-item')).toContainText('Keep lines under eight words.')
  await expect(card.getByRole('status')).toContainText('Added as a style rule.')
  if (SHOTS) { await page.waitForTimeout(800); await page.screenshot({ path: `${SHOTS}/d2-learned.png`, fullPage: true }) }
  await card.getByRole('button', { name: 'Remove Keep lines under eight words.' }).click()
  await expect(card.getByTestId('learned-item')).toHaveCount(0)
  await expect(card.getByRole('status')).toContainText('Removed. The rule is gone.')
  expect(calls).toEqual(['POST /api/projects/f1/learned/7/accept', 'DELETE /api/projects/f1/learned/7'])
})

// ── the editor: Discard, then why ────────────────────────────────────────────

const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4' }
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] }
const LINE = { text: 'Get thirty percent off today.', start: 0.2, end: 2.0, speaker: 'A' }
const TAKE = { candidate_id: 'c1', plan: { selection: { start: 0.2, end: 2.0 }, new_text: 'Now forty percent off today.', voice_profile_id: 'jeevan', mix: 'replace' },
  audio: { kind: 'audio', sha256: '1'.repeat(64), duration: 1.8, container: 'wav' }, frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 1.8, container: 'mp4' }, continuity: CONT, fit_notes: [] }

test('the editor: Discard asks why, optionally, and sends the picked reason', async ({ page }) => {
  let dismissed = false
  const posts: { path: string; body: string }[] = []
  const item = () => ({ item_id: 'i1', selection: { start: 0.2, end: 2.0 }, old_text: LINE.text, new_text: TAKE.plan.new_text, speaker: 'A', mix: 'replace', reason: 'The new offer.',
    kind: 'planned', enabled: !dismissed, status: dismissed ? 'dismissed' : 'ready', fit: null, candidate: TAKE, edit_id: null, question: null, error: null, note: null, progress: null })
  const plan = () => ({ type: 'plan', plan_id: 'plan1', goal: 'The new offer', summary: '', mode: 'ask', status: 'done', created_at: AT, estimate: { items: 1, voice_characters: 30, usd: 0.01, seconds: 0 },
    findings: [], question: null, answers: [], log: [], spend_usd: 0.01, items: [item()] })
  const video = () => ({
    video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 2.3, media: MEDIA, created_at: AT, consent_granted_at: AT, stage: 'draft',
    brief_version: 1, made_with_brief: 1, brief_changed: false,
    transcript: LINE.text.split(' ').map((w, k, ws) => ({ text: w, start: LINE.start + (k * (LINE.end - LINE.start)) / ws.length, end: LINE.start + ((k + 0.9) * (LINE.end - LINE.start)) / ws.length })),
    statements: [LINE], speakers: [{ label: 'A', name: 'Jeevan', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
    plan: plan(), reading: { opening: 'One speaker, one line.', roles: [] }, suggestions: [], frames: [], edits: [],
    messages: [{ role: 'user', text: 'Make it forty percent', kind: 'say', seq: 1 }, { role: 'assistant', text: 'One line, ready to hear.', kind: 'say', seq: 2 }],
  })
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const path = new URL(url).pathname
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET') posts.push({ path, body: req.postData() ?? '' })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json(FLAGS)
    if (url.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/videos/p1')) return json(video())
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) return json({ jobs: [], turn: null })
    if (path === '/api/videos/p1/plans/plan1/items/i1/dismiss') { dismissed = true; return json({ ...plan(), decision_id: 41 }) }
    if (path === '/api/videos/p1/decisions/41/reason') return json({ decision_id: 41, reason: JSON.parse(req.postData() ?? '{}').reason })
    if (url.includes('/plans/plan1')) return json(plan())
    if (url.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
    if (url.includes('/messages')) return json([])
    if (url.endsWith('/projects/f1/rules')) return json({ rules: [], rules_version: 0 })
    if (url.endsWith('/arrangement')) return json(null, 404)
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [PROJECT] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0.01, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 1.2, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [{ voice_id: 'jeevan', name: 'Jeevan', description: '', gender: 'male', accent: null, age: null }] })
    if (url.includes('/suggestions')) return json({ suggestions: [] })
    if (url.includes('/comments')) return json({ comments: [], open: 0 })
    return json({})
  })
  await page.setViewportSize({ width: 1360, height: 950 })
  await page.goto('/#v/p1')
  const discard = page.getByRole('button', { name: /^Discard/ }).first()
  await expect(discard).toBeVisible()
  await discard.click()
  const why = page.getByTestId('discard-why')
  await expect(why).toContainText('Discarded the line at 0:00. Tell Voltage why? Optional.')
  if (SHOTS) { await page.waitForTimeout(800); await page.screenshot({ path: `${SHOTS}/d2-discard-why.png` }) }
  await why.getByRole('button', { name: 'Too long' }).click()
  await expect(why).toContainText('Thanks. Voltage learns from this in this project.')
  expect(posts.map((p) => p.path)).toEqual(['/api/videos/p1/plans/plan1/items/i1/dismiss', '/api/videos/p1/decisions/41/reason'])
  expect(JSON.parse(posts[1].body)).toEqual({ reason: 'Too long' })
})
