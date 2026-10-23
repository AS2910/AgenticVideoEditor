import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, request } from '@playwright/test'
import type { APIRequestContext, Locator, Page } from '@playwright/test'

/** Shared steps for the launch rehearsal journeys: the real stack, its dev outbox
 *  (emails are rows in Postgres), sign-up, the checks every journey makes while
 *  it waits, and a screenshot recorder stitched into a small H.264 video. */

const HERE = dirname(fileURLToPath(import.meta.url))
export const REPO = resolve(HERE, '../../..')
export const SAMPLE_CLIP = join(REPO, 'frontend/public/sample-ad.mp4')
export const PASSWORD = 'rehearsal-pass-2026'
const FFMPEG = process.env.FFMPEG ?? '/opt/homebrew/bin/ffmpeg'

/** A fresh address for this run: `<who>+<time><random>@rehearsal.test`. */
export const freshEmail = (who: string) => `${who}+${Date.now()}${Math.floor(Math.random() * 1000)}@rehearsal.test`

/** SQL on the rehearsal stack's Postgres (scripts/rehearsal.sh sql). */
export function sql(query: string): string {
  return execFileSync(join(REPO, 'scripts/rehearsal.sh'), ['sql', query], { cwd: REPO, encoding: 'utf8', timeout: 60_000 })
}

/** The newest link of `kind` sent to `to`, read from the dev outbox, waiting for it to be written. */
export async function outboxLink(page: Page, to: string, kind: string, pattern: RegExp): Promise<string> {
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    const body = sql(`select body from notify_outbox where to_addr='${to.replace(/'/g, "''")}' and kind='${kind}' order by id desc limit 1`)
    const hit = pattern.exec(body)
    if (hit) return hit[0]
    await page.waitForTimeout(1000)
  }
  const kinds = sql(`select kind from notify_outbox where to_addr='${to.replace(/'/g, "''")}'`)
  throw new Error(`No ${kind} email for ${to} in the outbox (it has: ${kinds.trim() || 'nothing'})`)
}

/** What a journey must never show: a visible error banner, or a server error behind the page. */
export function watchServer(page: Page): { errors: string[] } {
  const errors: string[] = []
  page.on('response', (r) => { if (r.status() >= 500) errors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`) })
  page.on('pageerror', (e) => errors.push(`page error: ${e.message}`))
  return { errors }
}

export async function noErrorBanner(page: Page): Promise<void> {
  const alerts = page.locator('[role=alert]:visible')
  const n = await alerts.count()
  const texts: string[] = []
  for (let i = 0; i < n; i++) {
    const t = (await alerts.nth(i).innerText().catch(() => '')).trim()
    if (t) texts.push(t)
  }
  expect(texts, 'no error banner on the page').toEqual([])
}

/** Make an account on the sign-in page (Terms accepted), then open the confirm link from the outbox. */
export async function signUp(page: Page, email: string, rec?: Recorder): Promise<void> {
  if (!/#invite\//.test(page.url())) {
    // Item 8: a signed-out visitor at / sees the landing page (its pricing read from the server).
    await page.goto('/')
    await expect(page.getByTestId('landing-pricing')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('plan-card').first()).toBeVisible()
    await page.goto('/#login')
  }
  await page.getByRole('button', { name: 'New here? Make an account' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  const make = page.getByRole('button', { name: 'Make my account' })
  await expect(make).toBeDisabled()                                   // the Terms come first
  await page.getByRole('checkbox', { name: /I accept the Terms/ }).check()
  await rec?.shot()
  await make.click()
  await expect(page.getByTestId('auth-notice')).toContainText('an email is on its way')
  await rec?.shot()
  const link = await outboxLink(page, email, 'verify_email', /https?:\/\/\S+\/api\/auth\/verify\?token=[\w-]+/)
  await page.goto(link)
}

/** An owner made through the API (its own cookie jar): signed up, confirmed, with the
 *  sample project and one uploaded clip in it. Used by the Reviewer and Editor journeys. */
export interface ApiOwner { api: APIRequestContext; email: string; sampleProject: string; videoId: string }
export async function makeOwner(page: Page, baseURL: string, opts: { privateClip?: boolean } = {}): Promise<ApiOwner> {
  const api = await request.newContext({ baseURL, extraHTTPHeaders: { 'X-Requested-With': 'voltage' } })
  const email = freshEmail('owner')
  const ok = async (r: Awaited<ReturnType<APIRequestContext['get']>>, what: string) => {
    if (!r.ok()) throw new Error(`${what}: ${r.status()} ${await r.text()}`)
    return r
  }
  await ok(await api.post('/api/auth/signup', { data: { email, password: PASSWORD, accept_terms: true } }), 'sign up')
  const link = await outboxLink(page, email, 'verify_email', /https?:\/\/\S+\/api\/auth\/verify\?token=[\w-]+/)
  await ok(await api.get(new URL(link).pathname + new URL(link).search), 'verify')
  const me = await (await ok(await api.get('/api/auth/me'), 'me')).json()
  if (!me.user) throw new Error('the API owner is not signed in after verifying')
  const sample = await (await ok(await api.post('/api/me/sample'), 'sample')).json()
  const video = await (await ok(await api.post('/api/videos', {
    multipart: { file: { name: 'spring-ad.mp4', mimeType: 'video/mp4', buffer: readFileSync(SAMPLE_CLIP) }, consent: 'true', project_id: sample.project_id },
    timeout: 120_000,
  }), 'upload')).json()
  if (opts.privateClip) {   // a standalone video nobody was shared
    await ok(await api.post('/api/videos', {
      multipart: { file: { name: 'private-ad.mp4', mimeType: 'video/mp4', buffer: readFileSync(SAMPLE_CLIP) }, consent: 'true' },
      timeout: 120_000,
    }), 'upload private')
  }
  return { api, email, sampleProject: sample.project_id, videoId: video.video_id }
}

export async function inviteAs(owner: ApiOwner, email: string, role: 'reviewer' | 'editor'): Promise<void> {
  const r = await owner.api.post('/api/workspace/invites', { data: { email, role, spend_limit_usd: null, ...(role === 'reviewer' ? { project_ids: [owner.sampleProject] } : {}) } })
  if (!r.ok()) throw new Error(`invite: ${r.status()} ${await r.text()}`)
}

export async function dropOwner(owner: ApiOwner): Promise<void> {
  await owner.api.delete('/api/account').catch(() => {})
  await owner.api.dispose()
}

/** An invited person: the invite email's link, sign up through it, confirm, accept, Home. */
export async function joinByInvite(page: Page, email: string, role: 'Reviewer' | 'Editor', rec?: Recorder): Promise<void> {
  const link = await outboxLink(page, email, 'workspace_invite', /https?:\/\/\S+#invite\/[\w.-]+/)
  await page.goto(link)
  await expect(page.getByTestId('sign-in-forms')).toBeVisible()
  await signUp(page, email, rec)
  // Back on the invite once the account is confirmed.
  await expect(page).toHaveURL(/#invite\//)
  const invite = page.getByTestId('invite')
  await expect(invite).toContainText(role)
  await rec?.shot()
  await invite.getByRole('button', { name: 'Accept invite' }).click()
  await expect(page.getByText(new RegExp(`as an? ${role}\\.`))).toBeVisible()
  await rec?.shot()
  await page.getByRole('link', { name: 'Open Home' }).click()
  await expect(page).toHaveURL(/#home$/)
  await expect(page.getByTestId('projects-side')).toBeVisible()
  await dismissTour(page)
}

/** The video on the page has loaded its media (a signed address that answered). */
export async function videoPlays(page: Page): Promise<void> {
  await expect.poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 60_000 }).toBeGreaterThanOrEqual(1)
}

/** Sign in with the email and password form. */
export async function signIn(page: Page, email: string): Promise<void> {
  const form = page.getByRole('form', { name: 'Sign in with email and password' })
  await form.getByLabel('Email').fill(email)
  await form.getByLabel('Password').fill(PASSWORD)
  await form.getByRole('button', { name: 'Sign in', exact: true }).click()
}

/** Home after signing in: the tour offer is put away so it does not cover the page. */
export async function dismissTour(page: Page): Promise<void> {
  const offer = page.getByTestId('tour-offer')
  if (await offer.isVisible().catch(() => false)) await offer.getByRole('button', { name: 'Not now' }).click()
  const gotIt = page.getByRole('button', { name: 'Got it' })
  if (await gotIt.isVisible().catch(() => false)) await gotIt.click()
}

/** Tour tips ("Got it") that have opened over the page are put away. */
export async function dismissTips(page: Page): Promise<void> {
  const tips = page.getByRole('button', { name: 'Got it' })
  for (let i = await tips.count(); i > 0; i--) await tips.first().click({ timeout: 5_000 }).catch(() => {})
}

/** Take a turn and see it through: a working status shows the whole time; the gate
 *  (Check with me) is answered Go ahead; the proposal row lands, Proposed. */
export async function turnToProposal(page: Page, ask: string, rec?: Recorder): Promise<Locator> {
  const box = page.getByLabel('Describe a change')
  await expect(box).toBeEditable()
  await box.fill(ask)
  await box.press('Enter')
  const status = page.getByTestId('pane-status')
  await expect(status).toContainText(/working|reading|planning|voicing|thinking/i, { timeout: 30_000 })
  await rec?.shot()
  const proposal = page.locator('[role=listitem][aria-label^="Proposed line"]').filter({ hasText: 'Fresh every morning.' })
  const go = page.locator('[data-testid=clarify]:not([data-resolved])').getByRole('button', { name: 'Go ahead' })
  const deadline = Date.now() + 150_000
  while (Date.now() < deadline) {
    if (await proposal.getByRole('button', { name: /Add it/ }).count()) break
    if (await page.getByTestId('liveness').isVisible().catch(() => false)) {
      await giveConsent(page, rec)
      continue
    }
    if (await go.isEnabled({ timeout: 1_000 }).catch(() => false)) {
      await go.click()
      await rec?.shot()
      continue
    }
    await dismissTips(page)
    // While Voltage works, the user always sees what it is doing.
    const said = (await status.innerText().catch(() => '')).trim()
    expect(said, 'the pane says what Voltage is doing').not.toBe('')
    await page.waitForTimeout(1000)
  }
  await expect(proposal).toHaveAttribute('data-state', 'ready', { timeout: 5_000 })
  // data-state "ready" is the row's Proposed state. Its chip says what is happening to it
  // (Rendering the preview), then settles: Ready to hear, or In the preview once the
  // with-proposals preview carries it (rehearsal item 7: no longer "In the video").
  const chip = proposal.getByTestId('row-chip')
  await expect(chip).toHaveAttribute('data-status', /ready|rendering|in-preview|voicing|queued/)
  await expect(chip).toHaveAttribute('data-status', /^(ready|in-preview)$/, { timeout: 150_000 })
  // The turn ends (its preview rendered); then the row's Add it is live.
  await expect(proposal.getByRole('button', { name: /Add it/ })).toBeEnabled({ timeout: 150_000 })
  await expect(status).not.toContainText(/working/i)
  await rec?.shot()
  return proposal
}

/** The first voice in a project asks for the speaker's permission and a read-aloud
 *  recording (test mode: the liveness check is a stand-in). The sample clip is uploaded as it. */
export async function giveConsent(page: Page, rec?: Recorder): Promise<void> {
  const live = page.getByTestId('liveness')
  const tip = live.getByRole('button', { name: 'Got it' })
  if (await tip.isVisible().catch(() => false)) await tip.click()
  await expect(page.getByTestId('liveness-sentence')).not.toHaveText('Making a sentence…')
  await live.locator('input[type=file]').setInputFiles(SAMPLE_CLIP)
  await expect(page.getByTestId('liveness-note')).toContainText('Recorded.', { timeout: 60_000 })
  await rec?.shot()
  await page.getByRole('button', { name: 'Yes, I have it' }).click()
  await expect(live).toBeHidden({ timeout: 30_000 })
}

/** Add the proposal and wait for the row to say it is in the video. */
export async function addProposal(page: Page, proposal: Locator, rec?: Recorder): Promise<void> {
  await dismissTips(page)
  await proposal.getByRole('button', { name: /Add it/ }).click()
  const added = page.locator('[role=listitem][aria-label^="Added line"][data-state="kept"]').filter({ hasText: 'Fresh every morning.' })
  await expect(added).toBeVisible({ timeout: 90_000 })
  await rec?.shot()
}

/** Delete the account from Settings (typed DELETE), land signed out, and see signing in again fail. */
export async function deleteAccount(page: Page, email: string, rec?: Recorder): Promise<void> {
  await page.goto('/#settings')
  await page.getByRole('button', { name: 'Delete…' }).click()
  const ask = page.getByRole('group', { name: 'Delete everything?' })
  await ask.getByRole('textbox').fill('DELETE')
  await rec?.shot()
  await ask.getByRole('button', { name: 'Delete everything' }).click()
  // Signed out: the landing page (item 8), then the sign-in page.
  await expect(page.getByTestId('landing-pricing')).toBeVisible({ timeout: 60_000 })
  await rec?.shot()
  await page.goto('/#login')
  await expect(page.getByTestId('sign-in-forms')).toBeVisible({ timeout: 60_000 })
  await signIn(page, email)
  await expect(page.getByTestId('sign-in-forms').getByRole('alert')).toBeVisible()
  await expect(page.getByTestId('sign-in-forms')).toBeVisible()
  await rec?.shot()
}

/** Screenshots every ~500 ms of whichever page is on stage, stitched by the system
 *  ffmpeg into docs/rehearsal/<name>.mp4 (H.264, 720p at most). On only when
 *  REHEARSAL_VIDEO=1 (it costs a loaded machine some time). */
export class Recorder {
  private dir: string
  private n = 0
  private on: boolean
  private stopped = false
  private loop: Promise<void> | null = null
  private page: Page | null = null
  private name: string
  constructor(name: string) {
    this.name = name
    this.on = process.env.REHEARSAL_VIDEO === '1'
    this.dir = this.on ? mkdtempSync(join(tmpdir(), `rehearsal-${name}-`)) : ''
  }
  watch(page: Page): void {
    this.page = page
    if (!this.on || this.loop) return
    this.loop = (async () => {
      while (!this.stopped) {
        await this.shot()
        await new Promise((r) => setTimeout(r, 500))
      }
    })()
  }
  async shot(): Promise<void> {
    if (!this.on || !this.page || this.page.isClosed()) return
    const file = join(this.dir, `f${String(this.n++).padStart(5, '0')}.jpg`)
    await this.page.screenshot({ path: file, type: 'jpeg', quality: 70, timeout: 10_000 }).catch(() => { this.n-- })
  }
  async finish(): Promise<void> {
    this.stopped = true
    await this.loop
    if (!this.on || this.n === 0) return
    const out = join(REPO, 'docs/rehearsal', `${this.name}.mp4`)
    mkdirSync(dirname(out), { recursive: true })
    // Frames are ~500 ms apart: 2 frames a second plays the journey at about real time.
    const list = join(this.dir, 'frames.txt')
    writeFileSync(list, Array.from({ length: this.n }, (_, i) => `file 'f${String(i).padStart(5, '0')}.jpg'\nduration 0.5`).join('\n') + '\n')
    execFileSync(FFMPEG, ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list,
      '-vf', 'scale=1152:720:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2,fps=10',
      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out], { timeout: 300_000 })
    rmSync(this.dir, { recursive: true, force: true })
  }
}
