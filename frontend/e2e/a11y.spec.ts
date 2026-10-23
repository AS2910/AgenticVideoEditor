import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** Rehearsal item 7: every screen a public user can reach, in the public profile (API mocked),
 *  at desktop and at 375 px: axe finds no serious or critical issue, nothing scrolls sideways,
 *  and no page error or React warning is logged; desktop again in the dark theme. At 375 px (a touch phone) the screens a
 *  first visit meets (landing, sign-in, Home, the share and review pages, Billing, the policies)
 *  also keep every tap target at 44 px or more. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const AT = '2026-10-20T10:00:00Z'
const ago = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()
// What AVE_LAUNCH_PROFILE=public turns on (backend/app/flags.py PROFILES["public"]).
const PUBLIC_FLAGS = ['projects.consistency', 'golive.g1', 'golive.g2', 'golive.g3', 'golive.g4', 'golive.g6', 'golive.g7', 'golive.g8']
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true }
type Who = 'out' | 'owner' | 'editor' | 'reviewer'
const ROLE: Record<Exclude<Who, 'out'>, string> = { owner: 'owner', editor: 'editor', reviewer: 'reviewer' }

const PRICING = {
  trial_credits: 5, credit_usd: 1, topup_months: 12, test_mode: true, languages: false, invite_only: true,
  plans: [
    { plan_id: 'starter', name: 'Starter', credits: 15, blurb: 'For one person trying a few videos a month.', usd: 19, inr: 1599 },
    { plan_id: 'studio', name: 'Studio', credits: 50, blurb: 'For a small team shipping every week.', usd: 59, inr: 4999 },
    { plan_id: 'agency', name: 'Agency', credits: 160, blurb: 'For agencies running campaigns for clients.', usd: 179, inr: 14999 },
  ],
  topups: [{ credits: 10, usd: 12, inr: 1008 }, { credits: 25, usd: 30, inr: 2520 }],
}
const AUTH_OPTIONS = { mode: 'accounts', google: false, password: true, email_link: false, invite_only: true, terms_version: 'draft' }
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4' }
const LINE = { text: 'Get thirty percent off today.', start: 0.2, end: 2.0, speaker: 'A' }
const VIDEO = {
  video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 2.3, media: MEDIA, created_at: AT, consent_granted_at: AT, stage: 'draft',
  brief_version: 1, made_with_brief: 1, brief_changed: false,
  transcript: LINE.text.split(' ').map((w, k, ws) => ({ text: w, start: LINE.start + (k * 1.8) / ws.length, end: LINE.start + ((k + 0.9) * 1.8) / ws.length })),
  statements: [LINE], speakers: [{ label: 'A', name: 'Jeevan', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
  plan: null, reading: { opening: 'One speaker, one line.', roles: [] }, suggestions: [], frames: [], edits: [],
  messages: [{ role: 'user', text: 'Make it forty percent', kind: 'say', seq: 1 }, { role: 'assistant', text: 'One line, ready to hear.', kind: 'say', seq: 2 }],
}
const base = { duration: 31, edits: 0, state: 'new', last_change: 'Nothing changed yet', open_comments: 0, brief_changed: false, out_of_sync: false, stage: 'draft' }
const MORE = Array.from({ length: 11 }, (_, i) => ({ ...base, video_id: `q${i}`, project_id: 'f1', project_name: 'Diwali 2026', filename: `cut-${i}.mp4`, created_at: ago(60 + i), last_edited_at: ago(60 + i) }))
const VIDEOS = [
  ...MORE,
  { ...base, video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', created_at: ago(50), last_edited_at: ago(1) },
  { ...base, video_id: 'p2', project_id: null, project_name: null, filename: 'alone.mp4', created_at: ago(5), last_edited_at: ago(5) },
]
const FOLDER = { project_id: 'f1', name: 'Diwali 2026', brief: 'Brand is Bhaji Cam, said BAH-jee cam.', settings: { autonomy: 'ask', turn_usd: 0.5, effort: 'high' }, ceiling_usd: 10, spent_usd: 1.94,
  created_at: AT, video_count: 1, brief_version: 2, brief_edited_by: 'acct:9aaddbd873949cc9', brief_edited_by_name: 'ann@studio.test', brief_edited_at: ago(3), stale_count: 0 }
const DETAIL = {
  project: FOLDER, videos: VIDEOS.filter((v) => v.video_id === 'p1'),
  voices: [{ voice_id: 'v1', name: 'Diwali Narrator', kind: 'designed', seconds: 0, at: AT, used_in: 1, consent_granted_at: null, consent_needed: false }],
  files: [{ name: 'brand-guide.pdf', sha256: 'a'.repeat(64), size: 1200, kind: 'pdf', at: AT }],
  suggestions: [],
}
const RECEIPT = { turns: 4, takes: 6, spent_usd: 1.07, drafts: 0, render: { sha256: 'r'.repeat(64), duration: 2.3, filename: 'bhaji-cam-ad-edited.mp4' },
  changes: [{ edit_id: 'e1', start: 0.2, text: 'Now forty percent off today.', kind: 'changed', note: 'Customer\'s own voice' }] }
const plans = PRICING.plans.map((p) => ({ ...p, price: p.usd, currency: 'USD' }))
const BILLING = {
  account: { owner: 'acct:a1', plan: null, country: null, legal_name: '', gstin: '', state_code: null, created_at: '' },
  credits: { granted: 5, used: 1.2, left: 3.8, share: 0.24, minutes: null, grants: [] }, plan: null, plans,
  topups: [10, 25].map((c) => ({ credits: c, price: c * 1.2, currency: 'USD' })),
  provider: { name: 'stripe', label: 'Stripe (test mode)', test_mode: true }, trial_credits: 5, invoices: [], states: [{ code: '29', name: 'Karnataka' }],
}
const USAGE = { period: 'month', spent_usd: 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14,
  by_vendor: [{ vendor: 'elevenlabs', label: 'Voices', usd: 1.2 }], by_video: [{ video_id: 'p1', filename: 'bhaji-cam-ad.mp4', turns: 4, voice_characters: 300, spent_usd: 1.07, cap_usd: 2 }],
  by_project: [{ project_id: 'f1', name: 'Diwali 2026', videos: 1, turns: 4, spent_usd: 1.07, ceiling_usd: 10 }] }
const NOTIFY_KINDS = [{ kind: 'job_done', label: 'Long work finished', help: 'An export or an import that took more than a minute is done.', in_app: true, email: false },
  { kind: 'spend_alert', label: 'Spend alerts', help: 'A video, a project or the month reached 50%, 80% or 100% of its ceiling.', in_app: true, email: true }]
const MEMBERS = { workspace_id: 'w1', owner: { member: 'acct:a1', email: 'ann@studio.test', name: null, role: 'owner', role_word: 'Owner', spent_usd: 12.4 },
  members: [{ member: 'acct:e1', email: 'ed@studio.test', name: null, role: 'editor', role_word: 'Editor', spend_limit_usd: 20, spent_usd: 4.5, joined_at: AT, shares: [] }],
  invites: [], roles: [{ role: 'editor', word: 'Editor' }, { role: 'reviewer', word: 'Reviewer' }], sign_in: true }
const HELP = [{ slug: 'getting-started', section: 'Start here', title: 'Getting started', summary: 'Upload a video and ask for a change.', body: 'Upload a video, then say what to change.', tour: null, keywords: [] }]
const SHARE_EXPORT = { scope: 'export', role: 'viewer', name: null, expires_at: new Date(Date.now() + 86_400_000).toISOString(), exported_at: AT, title: 'Diwali 2026',
  files: [{ file_id: 'x1', name: 'bhaji-cam-ad-voltage.mp4', kind: 'video', size: MP4.length, duration: 2.3, label: null }] }
const SHARE_REVIEW = {
  scope: 'video', role: 'reviewer', name: 'Priya', expires_at: '2026-11-20T10:00:00.000Z', title: 'bhaji-cam-ad.mp4',
  files: [{ file_id: 'p1-v2', name: 'bhaji-cam-ad-voltage.mp4', kind: 'video', size: MP4.length, duration: 2.3, label: null, video_id: 'p1' }],
  review: { reviewer: 'Priya', allow_download: false, videos: [{ video_id: 'p1', title: 'bhaji-cam-ad.mp4', duration: 2.3, current_version: 2, answer: null, comments: [],
    versions: [{ version: 2, file_id: 'p1-v2', duration: 2.3, created_at: AT, against: 'as shot', changes: ['0:00 now says "Now forty percent off today."'] }] }] },
}

function me(who: Who) {
  if (who === 'out') return { mode: 'accounts', user: null }
  const id = { owner: 'a1', editor: 'e1', reviewer: 'r1' }[who]
  return { mode: 'accounts', user: { sub: id, email: `${who}@studio.test`, name: null, picture: null, provider: 'acct' } }
}

async function serve(page: Page, who: Who) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path.includes('/artifacts/') || path.includes('/files/') || path.endsWith('.mp4')) return route.fulfill({ status: 200, contentType: 'video/mp4', body: MP4 })
    if (path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/auth/me') return json(me(who))
    if (path === '/api/auth/options') return json(AUTH_OPTIONS)
    if (path === '/api/pricing') return json(PRICING)
    if (path === '/api/abuse-reports/open') return json({ open: true })
    if (path === '/api/share/sh1.sig') return json(SHARE_EXPORT)
    if (path === '/api/share/rv1.sig') return json(SHARE_REVIEW)
    if (path === '/api/invites/i1.abc') return json({ email: 'dev@client.test', role: 'reviewer', role_word: 'Reviewer', workspace_name: "ann@studio.test's workspace", invited_by: 'ann@studio.test', expires_at: '2026-11-04T00:00:00Z', sign_in: true })
    if (path === '/api/me/flags') return json({ flags: PUBLIC_FLAGS })
    if (path === '/api/me/onboarding') return json(ONBOARDING)
    if (path === '/api/me/admin') return json({ admin: false })
    if (path === '/api/me/media-token') return json({ token: 't', expires_at: new Date(Date.now() + 3_600_000).toISOString() })
    if (path === '/api/me/notifications/count') return json({ unread: 1 })
    if (path === '/api/me/notifications') return json({ items: [{ id: 1, kind: 'job_done', title: 'The export of bhaji-cam-ad.mp4 is done.', body: 'v2 ready', link: '#v/p1', video_id: 'p1', project_id: null, created_at: AT, read: false }], unread: 1 })
    if (path === '/api/me/notifications/settings') return json({ kinds: NOTIFY_KINDS })
    if (path === '/api/me/settings') return json({ autonomy: 'ask', turn_usd: 0.5, effort: 'high', ask_before: { ship: false, clone: true, design: false } })
    if (path === '/api/me/data-export') return json({ requests: [] })
    if (path === '/api/workspace') {
      const role = who === 'out' ? 'owner' : ROLE[who]
      const own = role === 'owner'
      return json({ workspace: { workspace_id: 'w1', name: own ? 'My workspace' : "ann@studio.test's workspace", own }, you: { user: `acct:${role[0]}1`, role },
        workspaces: own ? [{ workspace_id: 'w1', name: 'My workspace', role: 'owner', own: true }]
          : [{ workspace_id: 'w2', name: 'My workspace', role: 'owner', own: true }, { workspace_id: 'w1', name: "ann@studio.test's workspace", role, own: false }] })
    }
    if (path === '/api/workspace/members') return who === 'owner' ? json(MEMBERS) : json({ detail: 'Only the workspace owner can manage members and billing.' }, 403)
    if (path === '/api/billing') return who === 'owner' ? json(BILLING) : json({ detail: 'Only the workspace owner can manage members and billing.' }, 403)
    if (path === '/api/help') return json({ articles: HELP })
    if (path === '/api/pins') return json({ pins: [] })
    if (path === '/api/templates') return json({ templates: [] })
    if (path === '/api/projects') return json({ projects: url.searchParams.get('archived') === 'true' ? [] : [FOLDER] })
    if (path === '/api/projects/f1') return json(DETAIL)
    if (path === '/api/projects/f1/rules') return json({ rules: [], rules_version: 0 })
    if (path === '/api/projects/f1/briefs') return json({ current: 2, versions: [] })
    if (path === '/api/usage') return json(USAGE)
    if (path === '/api/spend') return json({ video: { spent_usd: 0.01, ceiling_usd: 2, label: 'This video' }, project: { spent_usd: 1.94, ceiling_usd: 10, label: 'Project Diwali 2026' }, month: { spent_usd: 1.2, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (path === '/api/voices') return json({ default: 'jeevan', voices: [{ voice_id: 'jeevan', name: 'Jeevan', description: 'Warm', gender: 'male', accent: null, age: null }], mine: [], project: [], slots: { used: 0, limit: 3 }, cloning: false })
    if (path === '/api/voices/made') return json({ voices: [] })
    if (path === '/api/voices/speakers') return json({ speakers: [] })
    if (path === '/api/videos') return json({ videos: VIDEOS })
    if (path === '/api/videos/p1') return json(VIDEO)
    if (path === '/api/videos/p1/receipt') return json(RECEIPT)
    if (path === '/api/videos/p1/jobs') return json({ jobs: [], turn: null })
    if (path === '/api/videos/p1/renders/latest') return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
    if (path === '/api/videos/p1/messages') return json([])
    if (path === '/api/videos/p1/arrangement') return json(null, 404)
    if (path === '/api/videos/p1/understanding') return json({ version: 1, read: { format: 'ad', genre: 'retail', summary: 'A shopkeeper offers a discount to camera.', setting: 'A small shop' },
      beats: [], corrections: [], style: { line: 'Warm, quick, one offer.', accepted: false, by: 'voltage' } })
    if (path === '/api/videos/p1/usage') return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (path === '/api/videos/p1/suggestions') return json({ suggestions: [] })
    if (path.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (method !== 'GET') return json({ ok: true })
    return json({})
  })
}

interface Screen { name: string; who: Who; hash: string; ready: (page: Page) => Promise<void>; targets?: boolean }
const visible = (testId: string) => async (page: Page) => { await expect(page.getByTestId(testId).first()).toBeVisible() }
const heading = (text: RegExp | string) => async (page: Page) => { await expect(page.getByRole('heading', { level: 1 })).toHaveText(text) }

const SCREENS: Screen[] = [
  // Signed out.
  { name: 'landing', who: 'out', hash: '/', ready: visible('plan-card'), targets: true },
  { name: 'welcome', who: 'out', hash: '/#welcome', ready: visible('plan-card'), targets: true },
  { name: 'login', who: 'out', hash: '/#login', ready: async (p) => { await expect(p.getByRole('button', { name: /Sign in|Create account/ }).first()).toBeVisible() }, targets: true },
  { name: 'reset', who: 'out', hash: '/#reset/tok1', ready: async (p) => { await expect(p.getByRole('heading', { level: 1 })).toBeVisible() }, targets: true },
  { name: 'invite', who: 'out', hash: '/#invite/i1.abc', ready: async (p) => { await expect(p.getByRole('button', { name: /Sign in|Create account/ }).first()).toBeVisible() }, targets: true },
  { name: 'terms', who: 'out', hash: '/#terms', ready: heading('Terms of service'), targets: true },
  { name: 'privacy', who: 'out', hash: '/#privacy', ready: heading('Privacy policy'), targets: true },
  { name: 'acceptable-use', who: 'out', hash: '/#acceptable-use', ready: visible('abuse-form'), targets: true },
  { name: 'share', who: 'out', hash: '/?share=1#s/sh1.sig', ready: visible('share-file'), targets: true },
  { name: 'review', who: 'out', hash: '/?share=2#s/rv1.sig', ready: async (p) => { await expect(p.getByRole('heading', { level: 1 })).toBeVisible() }, targets: true },
  // The owner.
  { name: 'home', who: 'owner', hash: '/#home', ready: visible('video-card'), targets: true },
  { name: 'project', who: 'owner', hash: '/#p/f1', ready: visible('brief') },
  { name: 'editor', who: 'owner', hash: '/#v/p1', ready: visible('transcript-list') },
  { name: 'editor-what-i-see', who: 'owner', hash: '/#v/p1', ready: async (p) => { await p.getByRole('button', { name: /What I see/i }).first().click(); await expect(p.getByRole('button', { name: 'Correct it' })).toBeVisible() } },
  { name: 'export', who: 'owner', hash: '/#v/p1/export', ready: async (p) => { await expect(p.getByRole('status').filter({ hasText: /Rendered/ }).first()).toBeVisible() } },
  { name: 'voices', who: 'owner', hash: '/#voices', ready: async (p) => { await expect(p.getByRole('heading', { level: 1 })).toBeVisible() } },
  { name: 'usage', who: 'owner', hash: '/#usage', ready: async (p) => { await expect(p.getByRole('heading', { level: 1 })).toBeVisible() } },
  { name: 'billing', who: 'owner', hash: '/#billing', ready: visible('credits-card'), targets: true },
  { name: 'settings', who: 'owner', hash: '/#settings', ready: visible('your-data') },
  { name: 'members', who: 'owner', hash: '/#members', ready: async (p) => { await expect(p.getByText('ed@studio.test').first()).toBeVisible() } },
  { name: 'help', who: 'owner', hash: '/#help', ready: async (p) => { await expect(p.getByRole('heading', { level: 1 })).toBeVisible() } },
  { name: 'notifications', who: 'owner', hash: '/#notifications', ready: async (p) => { await expect(p.getByText('Spend alerts').first()).toBeVisible() } },
  // An Editor and a Reviewer in the owner's workspace.
  { name: 'editor-home', who: 'editor', hash: '/#home', ready: visible('video-card') },
  { name: 'editor-editor', who: 'editor', hash: '/#v/p1', ready: visible('transcript-list') },
  { name: 'editor-members', who: 'editor', hash: '/#members', ready: async (p) => { await expect(p.getByRole('heading', { level: 1 })).toBeVisible() } },
  { name: 'editor-billing', who: 'editor', hash: '/#billing', ready: visible('billing-not-owner') },
  { name: 'reviewer-home', who: 'reviewer', hash: '/#home', ready: visible('reviewer-note'), targets: true },
  { name: 'reviewer-project', who: 'reviewer', hash: '/#p/f1', ready: visible('reviewer-note') },
  { name: 'reviewer-editor', who: 'reviewer', hash: '/#v/p1', ready: visible('read-only-note') },
  { name: 'reviewer-billing', who: 'reviewer', hash: '/#billing', ready: visible('billing-not-owner'), targets: true },
]

/** Serious and critical axe findings, one line each. */
async function axeProblems(page: Page): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
  return result.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.impact} ${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`)
}

/** Controls smaller than 44 px on a touch phone: buttons, fields, and links styled as buttons
 *  (a link inside a sentence is exempt, as WCAG 2.5.8 has it). */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = []
    const els = document.querySelectorAll<HTMLElement>('button, [role=button], input:not([type=hidden]):not(.sr-only), select, textarea, a.btn, a.act, nav a, [role=tab], [role=menuitem], summary')
    for (const el of els) {
      const r = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      if (r.width === 0 || r.height === 0 || style.visibility === 'hidden' || el.closest('[aria-hidden=true], [inert]')) continue
      if (el.classList.contains('sr-only')) continue
      // A checkbox or radio is reached through its label; the label is the target.
      if (el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio')) {
        const label = el.closest('label') ?? (el.id ? document.querySelector(`label[for="${el.id}"]`) : null)
        if (label) { const lr = label.getBoundingClientRect(); if (lr.height >= 44) continue }
      }
      if (r.height < 43.5 || r.width < 43.5) out.push(`${el.tagName.toLowerCase()} "${(el.getAttribute('aria-label') ?? el.textContent ?? '').trim().slice(0, 40)}" ${Math.round(r.width)}x${Math.round(r.height)}`)
    }
    return out
  })
}

for (const [label, width, height, scheme] of [['desktop', 1280, 900, 'light'], ['375 px', 375, 812, 'light'], ['desktop, dark', 1280, 900, 'dark']] as const) {
  test.describe(`public screens at ${label}`, () => {
    if (width === 375) test.use({ hasTouch: true, isMobile: true })
    for (const s of SCREENS) {
      test(`${s.name} (${s.who})`, async ({ page }) => {
        const errors: string[] = []
        page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
        page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|net::ERR/.test(m.text())) errors.push(`console: ${m.text().slice(0, 200)}`) })
        await page.setViewportSize({ width, height })
        // The entrance motion is off (prefers-reduced-motion), so axe reads each screen as it settles.
        await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: scheme })
        await serve(page, s.who)
        await page.goto(s.hash)
        await s.ready(page)
        await expect(page.getByRole('status', { name: /^Opening/ })).toHaveCount(0)
        await page.waitForTimeout(300)
        if (SHOTS) await page.screenshot({ path: `${SHOTS}/a11y-${s.name}-${width}-${scheme}.png`, fullPage: true })
        expect(await axeProblems(page), 'serious or critical axe issues').toEqual([])
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), 'no sideways scroll').toBeLessThanOrEqual(0)
        if (width === 375 && s.targets) expect(await smallTargets(page), 'tap targets under 44 px').toEqual([])
        expect(errors, 'no page errors or React warnings').toEqual([])
      })
    }
  })
}

test('the help menu\'s Send feedback dialog passes axe at 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await serve(page, 'owner')
  await page.goto('/#help')
  await page.getByRole('button', { name: 'Send feedback' }).click()
  await expect(page.getByTestId('feedback-dialog')).toBeVisible()
  expect(await axeProblems(page)).toEqual([])
})

test('the admin page (not public) still opens for an admin and passes axe', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, 'owner')
  await page.route('**/api/me/admin', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ admin: true }) }))
  await page.goto('/#admin')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.waitForTimeout(500)
  expect(await axeProblems(page)).toEqual([])
})
