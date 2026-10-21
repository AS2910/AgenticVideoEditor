import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** G6 in a real browser (API mocked): withdraw consent now in the editor; the policies are
 *  public and marked as drafts, with the abuse form; a shared link offers Report misuse;
 *  Settings downloads your data as a job. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const AT = '2026-10-20T10:00:00Z'
const FLAGS = { flags: ['projects.consistency', 'golive.g6'] }
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


async function serveEditor(page: Page, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const path = new URL(url).pathname
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET' && path !== '/api/analytics/events') posts.push(`${method} ${path}`)
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json(FLAGS)
    if (url.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/videos/p1/consent/withdraw') return json({ withdrawn: true, deleted: 1, failed: [], said: "Consent withdrawn. The speaker's voice clone was deleted at the voice service." })
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
}

test('G6: withdraw consent now deletes the clone, after one question', async ({ page }) => {
  const posts: string[] = []
  await page.setViewportSize({ width: 1360, height: 950 })
  await serveEditor(page, posts)
  await page.goto('/#v/p1')
  const row = page.getByTestId('withdraw-consent')
  await row.scrollIntoViewIfNeeded()
  await row.getByRole('button', { name: 'Withdraw consent now' }).click()
  await expect(row.getByRole('group', { name: 'Withdraw consent?' })).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g6-withdraw.png` })
  await row.getByRole('button', { name: 'Withdraw and delete the clone' }).click()
  await expect(page.getByText("Consent withdrawn. The speaker's voice clone was deleted at the voice service.")).toBeVisible()
  expect(posts).toEqual(['POST /api/videos/p1/consent/withdraw'])
})

test('G6: the policies are public drafts; misuse can be reported from them and from a shared link', async ({ page }) => {
  const reports: unknown[] = []
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path === '/api/abuse-reports/open') return json({ open: true })
    if (path === '/api/abuse-reports') { reports.push(JSON.parse(req.postData() ?? '{}')); return json({ report_id: 1, said: 'Thank you. We read every report and act on it.' }, 201) }
    if (path.endsWith('/auth/me')) return json({ mode: 'google', user: null })
    if (path === '/api/share/sh1.sig') return json({ scope: 'export', role: 'viewer', name: null, expires_at: new Date(Date.now() + 86_400_000).toISOString(), exported_at: AT, title: 'Diwali 2026', files: [] })
    return json({})
  })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#acceptable-use')                                       // signed out: still readable
  await expect(page.getByTestId('legal-draft')).toHaveText('Draft, needs legal review')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Acceptable use policy')
  const form = page.getByTestId('abuse-form')
  await form.getByLabel("Someone's voice used without their consent").check()
  await form.getByLabel('What happened (optional)').fill('My voice, without asking me')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g6-policy.png`, fullPage: true })
  await form.getByRole('button', { name: 'Send report' }).click()
  await expect(page.getByTestId('abuse-done')).toHaveText('Thank you. We read every report and act on it.')
  await page.goto('/?share=1#s/sh1.sig')                                  // a fresh load: a share link opens on its own
  await page.getByTestId('share-trust').getByRole('button', { name: 'Report misuse' }).click()
  await page.getByLabel("A public figure's voice").check()
  await page.getByRole('button', { name: 'Send report' }).click()
  await expect(page.getByTestId('abuse-done')).toBeVisible()
  expect(reports.map((r) => (r as { kind: string }).kind)).toEqual(['impersonation', 'public_figure'])
  expect((reports[1] as { location: string }).location).toContain('#s/sh1.sig')
})

test('G6: Settings downloads your data as a job', async ({ page }) => {
  let made = false
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    const done = { id: 1, kind: 'export', status: 'done', job_id: 'j9', created_at: AT, done_at: AT, job: { job_id: 'j9', kind: 'data_export', status: 'done', step_label: 'Ready', error_text: null } }
    if (path === '/api/me/data-export' && req.method() === 'POST') { made = true; return json({ request: done }, 202) }
    if (path === '/api/me/data-export') return json({ requests: made ? [done] : [] })
    if (path === '/api/abuse-reports/open') return json({ open: true })
    if (path === '/api/usage') return json({ period: 'month', spent_usd: 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14, by_vendor: [], by_project: [] })
    if (path === '/api/me/settings') return json({ autonomy: 'ask', turn_usd: 0.5, effort: 'high', ask_before: { ship: false, clone: true, design: false } })
    return json({})
  })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/#settings')
  const data = page.getByTestId('your-data')
  await data.scrollIntoViewIfNeeded()
  await data.getByRole('button', { name: 'Download my data' }).click()
  await expect(data.getByRole('link', { name: 'Download zip' })).toHaveAttribute('href', '/api/me/data-export/j9/download')
  await expect(page.getByRole('navigation', { name: 'Policies' })).toBeVisible()
})
