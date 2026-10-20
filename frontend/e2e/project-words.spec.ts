import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** A3 in a real browser (API mocked, nothing spent): the project's Words
 *  section, a proposal whose take broke a word rule, a banned word warned
 *  about while typing, and Learn a word from a selection in the transcript.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const AT = '2026-10-20T10:00:00Z'
const LINES = [
  { text: 'Hi, I want to buy groceries.', start: 0.5, end: 2.2, speaker: 'A' },
  { text: 'Start a live Bajicam session.', start: 2.6, end: 4.4, speaker: 'A' },
  { text: 'Sure, sir.', start: 4.8, end: 5.6, speaker: 'B' },
]
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 8, container: 'mp4' }
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] }
const BREAK = '“Bhaji Cam” did not come out as written (the take says “start a live badge cam session”).'
const ITEM = {
  item_id: 'i1', selection: { start: 2.6, end: 4.4 }, old_text: LINES[1].text, new_text: 'Start a live Bhaji Cam session.', speaker: 'A', mix: 'replace',
  reason: 'The brand name, said right.', kind: 'planned', enabled: true, status: 'ready', fit: null, edit_id: null, question: null, error: null, note: null, progress: null,
  word_rule: { breaks: [BREAK], warnings: [] },
  candidate: { candidate_id: 'c1', plan: { selection: { start: 2.6, end: 4.4 }, new_text: 'Start a live Bhaji Cam session.', voice_profile_id: 'v1', mix: 'replace' },
    audio: { kind: 'audio', sha256: '1'.repeat(64), duration: 1.8, container: 'wav' }, frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 1.8, container: 'mp4' }, continuity: CONT, fit_notes: [] },
}
const PLAN = { type: 'plan', plan_id: 'plan1', goal: 'Say the brand right', summary: '', mode: 'ask', status: 'done', created_at: AT, estimate: { items: 1, voice_characters: 30, usd: 0.01, seconds: 0 },
  findings: [], question: null, answers: [], log: [], spend_usd: 0, items: [ITEM] }
const VIDEO = {
  video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', brief_version: 1, made_with_brief: 1, brief_changed: false, filename: 'bhaji-cam-ad.mp4', duration: 8, media: MEDIA, created_at: AT,
  consent_granted_at: AT, transcript: LINES.flatMap((l) => l.text.split(' ').map((w, k, all) => ({ text: w, start: l.start + (k * (l.end - l.start)) / all.length, end: l.start + ((k + 1) * (l.end - l.start)) / all.length }))),
  statements: LINES, speakers: [{ label: 'A', name: 'Customer', voice_id: 'v1' }, { label: 'B', name: 'Shopkeeper', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
  plan: PLAN, reading: { opening: 'Two people in a shop.', roles: [] }, suggestions: [], frames: [], edits: [], messages: [],
}
type Rule = { rule_id: number; project_id: string; kind: string; data: Record<string, string>; version: number; created_by: string; updated_at: string }
const rule = (rule_id: number, kind: string, data: Record<string, string>): Rule => ({ rule_id, project_id: 'f1', kind, data, version: 1, created_by: 'local', updated_at: AT })

async function serve(page: Page, rules: Rule[], posts: { url: string; body: unknown }[]) {
  let next = 50
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method === 'POST' && !url.includes('/export')) posts.push({ url: new URL(url).pathname, body: req.postDataJSON?.() ?? null })
    if (url.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json({ flags: ['projects.consistency'] })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-upload', 'first-question'], checklist: [], checklist_hidden: true })
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/projects/f1/rules') && method === 'GET') return json({ rules, rules_version: rules.length })
    if (url.endsWith('/projects/f1/rules') && method === 'POST') {
      const body = req.postDataJSON() as { kind: string; data: Record<string, string> }
      const made = rule(next++, body.kind, body.data)
      rules.push(made)
      return json(made, 201)
    }
    if (url.endsWith('/projects/f1/brief-update')) return json({ run: null })
    if (url.endsWith('/projects/f1')) return json({ project: { project_id: 'f1', name: 'Diwali 2026', brief: 'Say Bhaji Cam as BAH-jee cam.', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0, created_at: AT, brief_version: 1, brief_edited_by: 'local', brief_edited_at: AT, stale_count: 0 },
      videos: [{ video_id: 'p1', project_id: 'f1', filename: 'bhaji-cam-ad.mp4', duration: 8, created_at: AT, edits: 0, state: 'draft', last_change: '1 proposed', made_with_brief: null, brief_changed: false }], voices: [], files: [], suggestions: [] })
    if (url.endsWith('/videos/p1')) return json(VIDEO)
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) return json({ jobs: [], turn: null })
    if (url.includes('/plans/plan1')) return json(PLAN)
    if (url.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h0', stale: false, in_progress: null, latest: null })
    if (url.includes('/messages')) return json([])
    if (url.endsWith('/arrangement')) return json(null, 404)
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [{ project_id: 'f1', name: 'Diwali 2026', brief: 'Say Bhaji Cam as BAH-jee cam.', ceiling_usd: null, spent_usd: 0, created_at: AT, video_count: 1 }] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [{ voice_id: 'v1', name: 'Brian', description: '', gender: 'male', accent: null, age: null }] })
    if (url.includes('/suggestions')) return json({ suggestions: [] })
    return json({})
  })
}

test('the Words section keeps how terms are said, banned words and required lines', async ({ page }) => {
  const posts: { url: string; body: unknown }[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, [rule(1, 'pronounce', { term: 'Bhaji Cam', say: 'BAH-jee cam', respell: 'Bah jee cam' })], posts)
  await page.goto('/#p/f1')
  const words = page.getByRole('region', { name: 'Words' })
  await expect(words.getByTestId('word-row')).toContainText('Bhaji Cam')
  await expect(words.getByTestId('word-row')).toContainText('Bah jee cam')
  await words.getByLabel('Term', { exact: true }).fill('Diwali')
  await words.getByLabel('How to say it').fill('dih-VAH-lee')
  await words.getByRole('button', { name: '+ Add word' }).click()
  await expect(words.getByTestId('word-row')).toHaveCount(2)
  await words.getByLabel('Banned word', { exact: true }).fill('cheap')
  await words.getByTestId('banned-words').getByRole('button', { name: '+ Add' }).click()
  await expect(words.getByTestId('banned-words')).toContainText('cheap')
  await words.getByLabel('Required line', { exact: true }).fill('T&C apply')
  await words.getByTestId('required-lines').getByRole('button', { name: '+ Add' }).click()
  await expect(words.getByTestId('required-lines')).toContainText('“T&C apply”')
  expect(posts.filter((p) => p.url === '/api/projects/f1/rules').map((p) => (p.body as { kind: string }).kind)).toEqual(['pronounce', 'banned', 'required_line'])
  if (SHOTS) await words.screenshot({ path: `${SHOTS}/a3-words.png` })
})

test('in the editor: a broken word rule is marked, a banned word is warned about, and a selected word can be learned', async ({ page }) => {
  const posts: { url: string; body: unknown }[] = []
  await page.setViewportSize({ width: 1440, height: 900 })
  await serve(page, [rule(1, 'banned', { word: 'cheap' })], posts)
  await page.goto('/#v/p1')
  const mark = page.getByTestId('word-rule')
  await expect(mark).toContainText('Breaks a word rule')
  await expect(mark).toContainText('did not come out as written')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a3-mark.png` })
  // The first time, a tip says what the mark means; Got it puts it away.
  await expect(page.getByRole('status', { name: 'Tip: Word rule' })).toBeVisible()
  await page.getByRole('button', { name: 'Got it' }).click()

  // Learn a word: double-click selects it in the transcript; the offer appears beside it.
  await page.getByText('Hi, I want to buy groceries.').dblclick()
  const learn = page.getByTestId('learn-word')
  await learn.getByRole('button', { name: 'Add to project words' }).click()
  const form = learn.getByRole('form', { name: 'Add to project words' })
  await expect(form.getByLabel('Term')).toHaveValue(/groceries|Hi|want|buy|I/)
  await form.getByLabel('Term').fill('Bajicam')
  await form.getByLabel('How to say it').fill('BAH-jee cam')
  await form.getByLabel('Respell (optional)').fill('Bah jee cam')
  await form.getByRole('button', { name: 'Add word' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Added “Bajicam” to Diwali 2026' })).toBeVisible()
  const added = posts.find((p) => p.url === '/api/projects/f1/rules')
  expect(added?.body).toEqual({ kind: 'pronounce', data: { term: 'Bajicam', say: 'BAH-jee cam', respell: 'Bah jee cam' } })

  // A typed line with a banned word: warned, never blocked.
  await page.getByText('Sure, sir.').hover()
  await page.getByRole('group', { name: 'Actions for 0:04' }).getByRole('button', { name: 'Edit it' }).click()
  const box = page.getByRole('textbox', { name: 'New wording' })
  await box.fill('Cheap groceries, delivered.')
  await expect(page.getByTestId('banned-warning')).toContainText('“cheap” is a banned word in this project. You can still voice it.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/a3-warning.png` })
  await box.press('Enter')
  await expect.poll(() => posts.some((p) => p.url === '/api/videos/p1/turns')).toBe(true)
})
