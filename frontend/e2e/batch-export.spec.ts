import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** B3 in a real browser (API mocked): the Presets section with its three
 *  defaults and a new preset, Export videos with every video picked (no
 *  stages without phase C, as in the public profile: run 5 item 9), the
 *  project check's warning, Export, rows that
 *  move from Queued and Rendering to Ready and Failed (with the reason),
 *  Download all and a share link; then F6's no-account share page, and an
 *  expired link's message. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString()
const STEP_S = 0.8

const VIDEOS = [
  { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', stage: 'approved' },
  { video_id: 'p3', filename: 'offer-cut.mp4', stage: 'approved' },
  { video_id: 'p4', filename: 'shop-tour.mp4', stage: 'draft' },
]
const LABEL: Record<string, string> = { draft: 'Draft', approved: 'Approved' }
const WARN = { kind: 'fact', message: 'The videos give different percentages: 20% in bhaji-cam-ad.mp4; 30% in offer-cut.mp4.', places: [], fingerprint: 'fp4' }
const preset = (preset_id: number, name: string, platform: string, extra = {}) => ({ preset_id, project_id: 'f1', name, platform, codec: 'h264', loudness: -14, captions: false,
  pattern: '{project}_{video}_{lang}_{preset}_v{version}', position: preset_id, created_by: 'local', created_at: ago(1), updated_at: ago(1), ...extra })
const slug = (s: string) => s.replace(/\.mp4$/, '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '')

class World {
  presets = [preset(1, 'YouTube 16:9', 'youtube'), preset(2, 'Reels 9:16', 'reels'), preset(3, 'Feed 1:1', 'feed')]
  started: { video_ids: string[]; preset_ids: number[] } | null = null
  at = 0
  shared = false
  page() {
    return { presets: this.presets, platforms: [{ id: 'youtube', label: 'YouTube 16:9', width: 1920, height: 1080 }, { id: 'reels', label: 'Reels 9:16', width: 1080, height: 1920 }, { id: 'feed', label: 'Feed 1:1', width: 1080, height: 1080 }],
      codecs: [{ id: 'h264', label: 'H.264', available: true }, { id: 'hevc', label: 'HEVC (H.265)', available: true }],
      loudness: [{ lufs: -14, label: 'Web · -14 LUFS' }, { lufs: -16, label: 'General · -16 LUFS' }, { lufs: -24, label: 'Broadcast · -24 LUFS' }],
      tokens: ['project', 'video', 'lang', 'preset', 'version'], default_pattern: '{project}_{video}_{lang}_{preset}_v{version}', captions: true }
  }
  run() {
    if (!this.started) return null
    const e = (Date.now() - this.at) / 1000
    const items = this.started.video_ids.flatMap((v) => this.started!.preset_ids.map((p) => ({ v, p })))
    const files = items.map(({ v, p }, index) => {
      const video = VIDEOS.find((x) => x.video_id === v)!
      const pr = this.presets.find((x) => x.preset_id === p)!
      const start = Math.floor(index / 2) * STEP_S
      const state = e < start ? 'queued' : e < start + STEP_S ? (v === 'p4' ? 'retrying' : 'rendering') : v === 'p4' ? 'failed' : 'ready'
      const name = `Diwali-2026_${slug(video.filename)}_en_${slug(pr.name)}_v2.mp4`
      return { index, video_id: v, filename: video.filename, stage: video.stage, approved: video.stage === 'approved', preset: pr, attempts: state === 'retrying' || state === 'failed' ? 2 : 1, job_id: `J${index + 20}`,
        state, label: { queued: 'Queued', rendering: 'Rendering', retrying: 'Trying again', ready: 'Ready', failed: 'Failed' }[state], why: state === 'failed' ? 'The render failed twice. The encoder ran out of memory.' : state === 'retrying' ? 'The first try failed; trying once more.' : null,
        file: state === 'ready' ? { name, size: 4_200_000, version: 2, duration: 30, report: { framing: pr.platform === 'youtube' ? 'Fills the frame.' : 'Letterboxed: black bars of 656 px above and below, nothing cropped.', width: 1080, height: 1920, loudness_lufs: -14, loudness_target: -14, captions: 0 } } : null }
    })
    const done = files.filter((f) => f.state === 'ready' || f.state === 'failed').length
    const ready = files.filter((f) => f.state === 'ready').length
    const failed = files.filter((f) => f.state === 'failed').length
    const over = done === files.length
    return { export_id: 'J19', project_id: 'f1', created_at: ago(0), finished_at: over ? ago(0) : null, phase: over ? 'finished' : 'running', status: over ? 'done' : 'running',
      step: `${ready} of ${files.length} files ready${over && failed ? `, ${failed} failed` : ''}`, progress: done / files.length, warnings: [WARN], files,
      counts: { total: files.length, ready, failed },
      share: this.shared ? { share_id: 'sh1', scope: 'export', target: 'J19', role: 'viewer', name: null, created_at: ago(0), expires_at: new Date(now + 30 * 86_400_000).toISOString(), revoked_at: null, state: 'live', url: 'http://localhost:5173/#s/sh1.sig' } : null }
  }
}

async function mockApi(page: Page, world: World, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const path = new URL(url).pathname
    const method = route.request().method()
    const body = route.request().postData() ?? ''
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path} ${body}`.trim())
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json({ flags: ['projects.batch'] })
    if (url.endsWith('/me/onboarding')) return json({ tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true })
    if (url.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/projects/f1/export-presets' && method === 'POST') {
      const made = preset(4, JSON.parse(body).name, JSON.parse(body).platform, JSON.parse(body))
      world.presets = [...world.presets, made]
      return json(made, 201)
    }
    if (path === '/api/projects/f1/export-presets') return json(world.page())
    if (path === '/api/projects/f1/exports/preflight') return json({ videos: VIDEOS.map((v) => ({ ...v, duration: 30, stage_label: LABEL[v.stage], approved: v.stage === 'approved' })), warnings: [WARN] })
    if (path === '/api/projects/f1/exports' && method === 'POST') { world.started = JSON.parse(body); world.at = Date.now(); return json(world.run(), 201) }
    if (path === '/api/projects/f1/exports') return json({ exports: world.run() ? [world.run()] : [] })
    if (path === '/api/projects/f1/exports/J19/share') { world.shared = true; return json(world.run()!.share, 201) }
    if (path === '/api/projects/f1/batches') return json({ batches: [] })
    if (path === '/api/projects/f1') return json({ project: { project_id: 'f1', name: 'Diwali 2026', brief: '', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0, created_at: ago(9), brief_version: 1, stale_count: 0 },
      videos: VIDEOS.map((v) => ({ ...v, project_id: 'f1', duration: 30, created_at: ago(5), edits: 1, state: 'draft', last_change: '1 change in the file' })), voices: [], files: [], suggestions: [] })
    if (url.includes('/spend')) return json({ project: { spent_usd: 0, ceiling_usd: null, label: 'Project Diwali 2026' }, month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    return json({})
  })
}

test('batch export: presets, pick videos and presets, warnings, files Ready and Failed, zip and a share link', async ({ page }) => {
  const world = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockApi(page, world, posts)
  await page.goto('/#p/f1')

  const presets = page.getByTestId('export-presets')
  await expect(presets.getByTestId('preset')).toHaveCount(3)
  await expect(presets.getByTestId('preset').nth(1)).toContainText('Reels 9:16 · H.264 · -14 LUFS · No captions')
  await presets.getByRole('button', { name: '+ Add preset' }).click()
  const form = presets.getByTestId('preset-form')
  await form.getByLabel('Name', { exact: true }).fill('TV spot')
  await form.getByRole('button', { name: 'Broadcast · -24 LUFS' }).click()
  await form.getByRole('checkbox').check()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b3-preset.png`, fullPage: true })
  await form.getByRole('button', { name: 'Save preset' }).click()
  await expect(presets.getByTestId('preset')).toHaveCount(4)
  await expect(presets.getByTestId('preset').nth(3)).toContainText('YouTube 16:9 · H.264 · -24 LUFS · Captions burned in')
  expect(posts.some((p) => p.startsWith('POST /api/projects/f1/export-presets') && p.includes('"loudness":-24') && p.includes('"captions":true'))).toBe(true)

  const panel = page.getByTestId('batch-export')
  const rows = panel.getByTestId('export-video')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0).getByRole('checkbox')).toBeChecked()
  await expect(rows.nth(1).getByRole('checkbox')).toBeChecked()
  await expect(rows.nth(2).getByRole('checkbox')).toBeChecked()
  await expect(panel).not.toContainText('Not approved')
  await expect(panel.getByTestId('export-warnings')).toContainText(WARN.message)
  await panel.getByRole('button', { name: 'Reels 9:16' }).click()
  await expect(panel.getByTestId('export-warnings')).toContainText('These are warnings. You can still export.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b3-pick.png`, fullPage: true })
  await panel.getByRole('button', { name: 'Export 6 files' }).click()
  expect(posts).toContain('POST /api/projects/f1/exports {"video_ids":["p2","p3","p4"],"preset_ids":[1,2]}')

  const runBox = panel.getByTestId('export-run')
  await expect(runBox).toContainText('Exporting 6 files')
  await expect(runBox.locator('[data-state="rendering"]')).toHaveCount(2)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b3-running.png`, fullPage: true })
  await expect(runBox).toContainText('Export finished', { timeout: 15_000 })
  await expect(runBox.getByTestId('export-step')).toHaveText('4 of 6 files ready, 2 failed')
  await expect(runBox.locator('[data-state="ready"]')).toHaveCount(4)
  const failed = runBox.locator('[data-state="failed"]')
  await expect(failed).toHaveCount(2)
  await expect(failed.first()).toContainText('The render failed twice. The encoder ran out of memory.')
  await expect(runBox.locator('[data-state="ready"]').first()).toContainText('Diwali-2026_bhaji-cam-ad_en_YouTube-16-9_v2.mp4')
  await expect(runBox.getByRole('link', { name: 'Download all (.zip)' })).toHaveAttribute('href', '/api/projects/f1/exports/J19/zip')
  await expect(page.getByRole('status', { name: 'Tip: Exported' })).toBeVisible()
  await page.getByRole('button', { name: 'Got it' }).click()
  await runBox.getByRole('button', { name: 'Share link' }).click()
  await expect(runBox.getByRole('textbox', { name: 'Share link' })).toHaveValue('http://localhost:5173/#s/sh1.sig')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/b3-finished.png`, fullPage: true })
})

test('the share page plays and downloads every file with no account; an expired link says so', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  let calls = 0
  await page.route('**/api/**', async (route: Route) => {
    const path = new URL(route.request().url()).pathname
    calls += 1
    if (path === '/api/share/sh1.sig') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ scope: 'export', role: 'viewer', name: null,
      expires_at: new Date(now + 30 * 86_400_000).toISOString(), exported_at: ago(0), title: 'Diwali 2026',
      files: [{ file_id: '0', name: 'Diwali-2026_bhaji-cam-ad_en_YouTube-16-9_v2.mp4', kind: 'video', size: 4_200_000, duration: 30, label: 'YouTube 16:9 · bhaji-cam-ad.mp4' },
        { file_id: '1', name: 'Diwali-2026_bhaji-cam-ad_en_Reels-9-16_v2.mp4', kind: 'video', size: 3_900_000, duration: 30, label: 'Reels 9:16 · bhaji-cam-ad.mp4' }] }) })
    if (path === '/api/share/sh2.old') return route.fulfill({ status: 410, contentType: 'application/json', body: JSON.stringify({ detail: 'This link has expired. Ask the person who shared it for a new one.' }) })
    if (path.includes('/files/')) return route.fulfill({ status: 404, body: '' })
    return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Sign in to continue.' }) })
  })
  await page.goto('/#s/sh1.sig')
  await expect(page.getByRole('heading', { name: 'Diwali 2026' })).toBeVisible()
  const files = page.getByTestId('share-file')
  await expect(files).toHaveCount(2)
  await expect(files.first().locator('video')).toHaveAttribute('src', '/api/share/sh1.sig/files/0')
  await expect(files.first().getByRole('link', { name: /^Download / })).toHaveAttribute('href', '/api/share/sh1.sig/files/0?download=true')
  await expect(page.getByRole('link', { name: 'Download all (.zip)' })).toHaveAttribute('href', '/api/share/sh1.sig/zip')
  await expect(page.getByText('Sign in')).toHaveCount(0)                  // no account asked for
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/f6-share.png`, fullPage: true })
  expect(calls).toBeGreaterThan(0)

  await page.goto('/#s/sh2.old')
  await page.reload()
  await expect(page.getByTestId('share-refused')).toContainText('This link has expired. Ask the person who shared it for a new one.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/f6-expired.png`, fullPage: true })
})
