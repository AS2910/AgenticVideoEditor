import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Voice consent V1 step 6, in a real browser against a scripted server (nothing spent).
 *  1. Clone, attest, voice, export reminder, export: a line edited in place goes to the
 *     quick route, which asks for the attestation (409); the modal confirms and the same
 *     edit goes through. Export asks for the reminder (409); it confirms (label kept on)
 *     and the export is made. The same journey with the flag off asks nothing; the extra
 *     clicks and time are measured and printed (CONSENT_COST lines).
 *  2. Voltage's turn paused on the attestation: the card is the modal's content in the
 *     pane; Use this voice posts the attestation and answers the card.
 *  3. A blocked line: the row and the chat say why, and Edit the line opens the editor.
 *  At the three sizes of the layout tests (shell.spec.ts). */

// SHOTS=<dir> saves the dialogs and cards (SHOTS_DARK=1: in the dark theme).
const SHOTS = process.env.SHOTS ?? ''
const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const SIZES: [number, number][] = [[1440, 900], [1280, 720], [1920, 1080]]
const AT = '2026-10-31T10:00:00Z'
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 12, container: 'mp4' }
const LINES = [
  { text: 'Our bread is baked every day.', start: 1.0, end: 4.0, speaker: 'A' },
  { text: 'Come in before nine.', start: 6.0, end: 9.0, speaker: 'A' },
]
const NEW = 'Our bread is baked fresh every day.'
const STATEMENT = '2026-10-31'
const ATTEST = { code: 'attestation_required', message: 'Tell us whose voice this is before Voltage makes new lines in it.', voice: 'A', voice_id: null,
  video_id: 'p1', source_video_id: 'p1', speaker_label: 'A', speaker_name: 'Asha', statement_version: STATEMENT }
const CONFIRM = { code: 'export_confirm_required', message: 'Confirm the AI voice reminder before you export this video.', export_ref: 'ex_1',
  voices: [{ voice_id: 'v-asha', video_id: 'p1', speaker_label: 'A', speaker_name: 'Asha' }], videos: ['p1'], statement_version: STATEMENT, label_default: true }
const BLOCKED = "I can't voice this line. It asks for payment details, which we don't allow."
const CONT = { voice_match: 0.95, prosody: 0.93, audio_integration: 0.97, lip_sync: null, passed: true, warnings: [], measured: ['prosody'] }

const item = (over: Record<string, unknown> = {}) => ({
  item_id: 'i1', selection: { start: 1.0, end: 4.0 }, old_text: LINES[0].text, new_text: NEW, speaker: 'A', mix: 'replace', reason: '', kind: 'planned',
  enabled: true, status: 'ready', fit: 'fit', edit_id: null, question: null, error: null, note: null, progress: null,
  candidate: { candidate_id: 'c1', plan: { selection: { start: 1.0, end: 4.0 }, new_text: NEW, voice_profile_id: 'v-asha', mix: 'replace' },
    audio: { kind: 'audio', sha256: '1'.repeat(64), duration: 2.8, container: 'wav' }, frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 2.8, container: 'mp4' }, continuity: CONT, fit_notes: [] },
  ...over,
})
const plan = (items: unknown[], over: Record<string, unknown> = {}) => ({ type: 'plan', plan_id: 'plan1', goal: 'Fresher', summary: '', mode: 'draft', status: 'done', created_at: AT,
  estimate: { items: 1, voice_characters: 30, usd: 0.01, seconds: 0 }, findings: [], question: null, answers: [], log: [], spend_usd: 0, items, ...over })

/** The scripted server. `on`: voices.cloning_verified. Every request the page sends is kept, in order. */
class World {
  attested = false
  confirmed: { label_on: boolean } | null = null
  voiced = false
  exported = false
  sent: { method: string; path: string; body: unknown; at: number }[] = []
  constructor(public on: boolean, public start: { plan?: unknown; messages?: unknown[] } = {}) {}
  plan() { return this.voiced ? plan([item()]) : this.start.plan ?? null }
}

async function serve(page: Page, w: World) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname.replace(/^\/api/, '')
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET') w.sent.push({ method, path, body: req.postDataJSON?.() ?? null, at: Date.now() })
    if (path.includes('/artifacts/')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (path === '/auth/me') return json({ mode: 'off', user: null })
    if (path === '/me/flags') return json({ flags: w.on ? ['voices.cloning_verified'] : [] })
    if (path === '/me/onboarding') return json({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-upload', 'first-question', 'first-take', 'first-thumbs'], checklist: [], checklist_hidden: true })
    if (path.includes('/events') || path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/videos/p1') {
      return json({ video_id: 'p1', project_id: null, project_name: null, filename: 'bakery.mp4', duration: 12, media: MEDIA, created_at: AT, consent_granted_at: AT,
        transcript: LINES.flatMap((l) => l.text.split(' ').map((t, k, ws) => ({ text: t, start: l.start + (k * (l.end - l.start)) / ws.length, end: l.start + ((k + 0.9) * (l.end - l.start)) / ws.length }))),
        statements: LINES, speakers: [{ label: 'A', name: 'Asha', voice_id: null }], settings: { autonomy: 'draft', turn_usd: 0.5 },
        plan: w.plan(), reading: { opening: 'One speaker, two lines.', roles: [] }, suggestions: [], frames: [], edits: [], messages: w.start.messages ?? [] })
    }
    // The fast path asks for the attestation itself (step 6), then voices the line as one take.
    if (path === '/videos/p1/lines/quick' && method === 'POST') {
      if (w.on && !w.attested) return json({ detail: ATTEST }, 409)
      return json({ job_id: 'Q1', kind: 'turn', project_id: 'p1', status: 'running', progress: 0, step: 'Voicing', attempts: 0, error: null, result: null, route: 'fast', reason: '1 word changed' }, 202)
    }
    if (path === '/jobs/Q1') {
      w.voiced = true
      return json({ job_id: 'Q1', kind: 'turn', project_id: 'p1', status: 'succeeded', progress: 1, step: 'Done', attempts: 0, error: null,
        result: { type: 'turn', quick: true, plan: w.plan(), reply: 'Voiced line 1 straight away. Hear it, then add it if it sounds right.', question: null, fallback: null, story: [] } })
    }
    if (/^\/videos\/p1\/voices\/[^/]+\/attest$/.test(path) && method === 'POST') {
      w.attested = true
      return json({ id: 'va_1', voice_id: null, speaker_label: 'A', choice: (req.postDataJSON() as { choice: string }).choice, statement_version: STATEMENT }, 201)
    }
    if (path === '/videos/p1/export' && method === 'POST') {
      if (w.on && !w.confirmed) return json({ detail: CONFIRM }, 409)
      w.exported = true
      return json({ segments: [], inserts: [], pieces: [], render: { kind: 'video', sha256: 'r'.repeat(64), duration: 12, container: 'mp4' }, proposals: [], edit_hash: 'h2', mode: 'final',
        cached: false, version: 2, render_id: 'r2', created_at: AT, includes: { item_ids: [], candidate_ids: [], edit_ids: [] } })
    }
    if (path === '/exports/ex_1/confirm' && method === 'POST') {
      w.confirmed = req.postDataJSON() as { label_on: boolean }
      return json({ id: 'ea_1', export_id: 'ex_1', label_on: w.confirmed.label_on }, 201)
    }
    if (path === '/videos/p1/receipt') {
      return json({ turns: 1, takes: 1, spent_usd: 0.01, drafts: 0, changes: [],
        render: w.exported ? { sha256: 'r'.repeat(64), duration: 12, filename: 'bakery-edited.mp4' } : null })
    }
    if (path === '/videos/p1/turns' && method === 'POST') {
      return json({ job_id: 'T2', kind: 'turn', project_id: 'p1', status: 'running', progress: 0, step: 'Thinking', attempts: 0, error: null, result: null }, 202)
    }
    if (path === '/jobs/T2') return json({ job_id: 'T2', kind: 'turn', project_id: 'p1', status: 'succeeded', progress: 1, step: 'Done', attempts: 0, error: null, result: { type: 'turn', plan: plan([item()]), reply: 'Voiced.', question: null } })
    if (path === '/voices/scopes') return json({ voices: [] })
    if (/^\/videos\/p1\/jobs$/.test(path)) return json({ jobs: [], turn: null })
    if (path.includes('/plans/plan1')) return json(w.plan())
    if (path.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
    if (path.includes('/messages')) return json([])
    if (path.endsWith('/arrangement')) return json(null, 404)
    if (path === '/videos') return json({ videos: [] })
    if (path === '/projects') return json({ projects: [] })
    if (path.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (path.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (path.includes('/spend')) return json({ video: { spent_usd: 0, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (path === '/voices') return json({ default: 'mock', voices: [{ voice_id: 'mock', name: 'Jeevan', description: '', gender: 'male', accent: null, age: null }] })
    if (path.includes('/suggestions')) return json({ suggestions: [] })
    return json({})
  })
}

/** Clicks the person makes, counted (the journey's cost is the difference with the flag off). */
class Clicks {
  n = 0
  async click(l: ReturnType<Page['locator']>) { this.n += 1; await l.click() }
}

/** The journey: edit a line in place (Voltage clones Asha's voice for it), hear it voiced, then export. */
async function journey(page: Page, w: World, size: [number, number]) {
  const c = new Clicks()
  await page.setViewportSize({ width: size[0], height: size[1] })
  if (process.env.SHOTS_DARK) await page.emulateMedia({ colorScheme: 'dark' })
  await serve(page, w)
  await page.goto('/#v/p1')
  const row = page.getByRole('listitem', { name: /Line at 0:01/ })
  await expect(row).toBeVisible()
  const t0 = Date.now()
  await row.hover()
  await c.click(page.getByRole('group', { name: 'Actions for 0:01' }).getByRole('button', { name: 'Edit it' }))
  const box = page.getByRole('textbox', { name: 'New wording' })
  await box.fill(NEW)
  await box.press('Enter'); c.n += 1
  let consentMs = 0
  if (w.on) {
    // The attestation, exactly the plan's words, opened by the quick route's 409.
    const t = Date.now()
    const modal = page.getByRole('dialog', { name: "Use Asha's voice?" })
    await expect(modal).toBeVisible()
    await expect(modal).toContainText("Voltage will make new lines in this person's voice. Tell us whose voice it is.")
    await expect(modal).toContainText("Using someone's voice without their consent can be illegal.")
    const accept = modal.getByRole('button', { name: 'Use this voice' })
    await expect(accept).toBeDisabled()
    if (SHOTS) await page.waitForTimeout(1000).then(() => page.screenshot({ path: `${SHOTS}/attest-${size[0]}.png` }))
    await c.click(modal.getByRole('radio', { name: 'This is my voice' }))
    await c.click(modal.getByRole('checkbox', { name: /I confirm I have the rights and consent/ }))
    await c.click(accept)
    await expect(modal).toHaveCount(0)
    consentMs += Date.now() - t
  }
  // The same edit went through: the take is ready to hear on the row.
  await expect(row.getByTestId('row-chip')).toHaveText('Ready to hear', { timeout: 15_000 })
  await c.click(page.getByTestId('editor-header').getByRole('link', { name: /Export/ }))
  if (w.on) {
    const t = Date.now()
    const reminder = page.getByRole('dialog', { name: "This video has AI changes to Asha's voice" })
    await expect(reminder).toBeVisible()
    await expect(reminder.getByRole('checkbox', { name: 'Add an "AI voice" label to the video (recommended)' })).toBeChecked()
    const go = reminder.getByRole('button', { name: 'Export' })
    await expect(go).toBeDisabled()
    if (SHOTS) await page.waitForTimeout(1000).then(() => page.screenshot({ path: `${SHOTS}/reminder-${size[0]}.png` }))
    await c.click(reminder.getByRole('checkbox', { name: 'I have permission from everyone whose voice was changed' }))
    await c.click(go)
    await expect(reminder).toHaveCount(0)
    consentMs += Date.now() - t
  }
  await expect(page.getByRole('link', { name: /Download MP4/ })).toBeVisible({ timeout: 15_000 })
  return { clicks: c.n, ms: Date.now() - t0, consentMs }
}

for (const size of SIZES) {
  test(`clone, attest, voice, export reminder, export at ${size[0]}x${size[1]}; the flag off asks nothing`, async ({ browser }) => {
    const on = new World(true)
    const onPage = await browser.newPage()
    const withConsent = await journey(onPage, on, size)
    expect(on.attested && on.voiced && on.exported).toBe(true)
    expect(on.confirmed).toEqual({ label_on: true })
    const quick = on.sent.filter((s) => s.path === '/videos/p1/lines/quick')
    expect(quick).toHaveLength(2)                                        // asked, then the same edit once more
    expect(quick[1].body).toEqual(quick[0].body)
    expect(on.sent.find((s) => s.path.endsWith('/attest'))?.body).toEqual({ choice: 'my_voice', statement_version: STATEMENT })
    expect(on.sent.filter((s) => s.path === '/videos/p1/turns')).toHaveLength(0)       // never a full turn
    expect(on.sent.filter((s) => s.path === '/exports/ex_1/confirm')).toHaveLength(1)
    await onPage.close()

    const off = new World(false)
    const offPage = await browser.newPage()
    const without = await journey(offPage, off, size)
    expect(off.sent.some((s) => s.path.endsWith('/attest') || s.path.startsWith('/exports/'))).toBe(false)
    await offPage.close()

    const extra = { clicks: withConsent.clicks - without.clicks, ms: withConsent.ms - without.ms, inDialogsMs: withConsent.consentMs }
    console.log(`CONSENT_COST ${size[0]}x${size[1]} ${JSON.stringify({ on: withConsent, off: without, extra })}`)
    expect(extra.clicks).toBe(5)                           // radio, box, Use this voice; box, Export
  })

  test(`Voltage's turn pauses on the attestation card in the pane at ${size[0]}x${size[1]}`, async ({ page }) => {
    const asked = { text: "Use Asha's voice?", options: ['Use this voice', 'Cancel'], guess: 'Use this voice', gate: false, kind: 'attestation_required', attestation: { ...ATTEST, voice: 'v-asha', voice_id: 'v-asha' } }
    const w = new World(true, {
      plan: plan([item({ status: 'needs-you', candidate: null })], { status: 'clarifying', question: asked }),
      messages: [{ role: 'user', text: 'Make line 1 fresher', kind: 'say', seq: 1 }],
    })
    await page.setViewportSize({ width: size[0], height: size[1] })
    await serve(page, w)
    await page.goto('/#v/p1')
    const card = page.getByTestId('attestation-card')
    await expect(card).toBeVisible()
    await expect(card).toContainText("Use Asha's voice?")
    await expect(card).toContainText('I have permission from this person to change what they say')
    await expect(page.getByTestId('clarify')).toHaveCount(0)                // the card, never a plain question
    if (SHOTS) await page.waitForTimeout(1000).then(() => page.screenshot({ path: `${SHOTS}/card-${size[0]}.png` }))
    // The card is the newest item of the thread, and fits the pane (no sideways scroll).
    const pane = page.locator('.pane-thread')
    // The person's next action is reachable as the card appears: Use this voice and Cancel sit inside
    // the window and inside the thread's visible area, with no scrolling (the action row stays put).
    const inView = async (name: string) => {
      const b = await card.getByRole('button', { name }).boundingBox()
      const p = await pane.boundingBox()
      if (!b || !p) return false
      return b.y >= 0 && b.x >= 0 && b.y + b.height <= size[1] && b.x + b.width <= size[0]
        && b.y >= p.y && b.y + b.height <= p.y + p.height + 1 && b.x >= p.x && b.x + b.width <= p.x + p.width + 1
    }
    await expect.poll(() => inView('Use this voice'), { timeout: 5_000 }).toBe(true)
    await expect.poll(() => inView('Cancel')).toBe(true)
    // Focus is on the first choice, and the whole card stays in the accessibility tree.
    const first = card.getByRole('radio', { name: 'This is my voice' })
    await expect(first).toBeFocused()
    // Never under the action row: the focused choice ends above it.
    const fb = await first.boundingBox(), rb = await card.getByTestId('attest-actions').boundingBox()
    expect(fb && rb && fb.y + fb.height <= rb.y).toBe(true)
    await expect(card.getByTestId('attest-warning')).toBeVisible()
    expect(await pane.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await card.getByRole('radio', { name: 'I have permission from this person to change what they say' }).click()
    await card.getByRole('checkbox').click()
    await card.getByRole('button', { name: 'Use this voice' }).click()
    await expect.poll(() => w.sent.find((s) => s.path === '/videos/p1/turns')?.body).toMatchObject({ text: 'Use this voice' })
    const attest = w.sent.findIndex((s) => s.path === '/videos/p1/voices/v-asha/attest')
    const answer = w.sent.findIndex((s) => s.path === '/videos/p1/turns')
    expect(attest).toBeGreaterThanOrEqual(0)
    expect(attest).toBeLessThan(answer)                                      // attested first, then the turn goes on
    expect(w.sent[attest].body).toEqual({ choice: 'have_permission', statement_version: STATEMENT })
  })

  test(`a blocked line says why on the line and in the chat, with Edit the line, at ${size[0]}x${size[1]}`, async ({ page }) => {
    const words = 'Share the OTP you just got.'
    const w = new World(true, {
      plan: plan([item({ new_text: words, status: 'failed', candidate: null, error: BLOCKED })]),
      messages: [
        { role: 'user', text: 'Ask for the OTP', kind: 'say', seq: 1 },
        { role: 'assistant', text: `Could not voice “${words}”: ${BLOCKED}`, kind: 'step', seq: 2,
          data: { tool: 'synthesize_take', t: 1.2, refusal: { code: 'line_blocked', message: BLOCKED, item_id: 'i1', start: 1.0, end: 4.0 } } },
        { role: 'assistant', text: 'That line cannot be voiced.', kind: 'say', seq: 3 },
      ],
    })
    await page.setViewportSize({ width: size[0], height: size[1] })
    await serve(page, w)
    await page.goto('/#v/p1')
    const row = page.getByRole('listitem', { name: /Line at 0:01/ })
    await expect(row.getByTestId('line-blocked')).toContainText(BLOCKED)
    const note = page.getByTestId('refusal-note')
    await expect(note).toContainText(BLOCKED)
    if (SHOTS) await page.waitForTimeout(1000).then(() => page.screenshot({ path: `${SHOTS}/blocked-${size[0]}.png` }))
    await note.getByRole('button', { name: 'Edit the line' }).click()
    await expect(page.getByRole('textbox', { name: 'New wording' })).toHaveValue(words)
    await expect(page.getByRole('textbox', { name: 'New wording' })).toBeFocused()
  })
}
