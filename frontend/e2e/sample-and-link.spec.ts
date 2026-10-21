import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** G1 in a real browser (API mocked, nothing fetched for real): a new owner's
 *  first Home load makes the sample project (shown with its Sample stamp),
 *  and a pasted Dropbox link imports into the chosen project with progress,
 *  then opens the new video; a YouTube link is refused with its sentence.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const AT = '2026-10-21T10:00:00Z'
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse', 'golive.g1'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-home-search', 'first-sample'], checklist: [], checklist_hidden: true }
const SAMPLE = { project_id: 'f1', name: 'Sample: bhaji-cam ad', brief: '', settings: {}, ceiling_usd: null, spent_usd: 0, created_at: AT, video_count: 1, sample: true }
const VIDEO = { video_id: 'p1', project_id: 'f1', project_name: SAMPLE.name, filename: 'sample-ad.mp4', created_at: AT, duration: 2.3, edits: 0, state: 'new', last_change: '', stage: 'draft', open_comments: 0 }
const JOB = (extra: Record<string, unknown>) => ({ job_id: 'J4', video_id: 'user-local', kind: 'import', status: 'running', step_label: 'Downloading from Dropbox', progress: 0.4,
  line_ids: [], created_at: AT, started_at: AT, finished_at: null, eta_s: null, error_code: null, error_text: null, cost_usd: null, retryable: false, detail: {}, ...extra })

async function serve(page: Page, posts: string[]) {
  let made = false
  let polls = 0
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path} ${req.postData() ?? ''}`.trim())
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/me/sample') { const first = !made; made = true; return json({ created: first, project_id: 'f1' }) }
    if (path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/pins') return json({ pins: [] })
    if (path === '/api/projects') return json({ projects: made ? [SAMPLE] : [] })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: made ? [VIDEO] : [] })
    if (path === '/api/imports/sources') return json({ sources: [{ name: 'drive', label: 'Google Drive', enabled: true, why_off: null }, { name: 'dropbox', label: 'Dropbox', enabled: true, why_off: null }, { name: 'youtube', label: 'YouTube', enabled: false, why_off: 'x' }], max_bytes: 2147483648 })
    if (path === '/api/imports' && method === 'POST') {
      if ((req.postData() ?? '').includes('youtube')) return json({ detail: 'Importing from YouTube needs you to connect your Google account so Voltage can check the video is yours. That is not set up yet. Download it from YouTube Studio and upload the file instead.' }, 422)
      return json(JOB({ status: 'queued', step_label: 'Queued', progress: 0 }), 202)
    }
    if (path === '/api/imports/J4') {
      polls += 1
      return json(polls < 3 ? JOB({ detail: { bytes: 40 * 1024 ** 2, total_bytes: 100 * 1024 ** 2 } }) : JOB({ status: 'done', step_label: 'Ready', progress: 1, detail: { video_id: 'p9' } }))
    }
    return json({})
  })
}

test('G1: the sample project on first Home load, and import from a link', async ({ page }) => {
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 1000 })
  await serve(page, posts)
  await page.goto('/')
  const side = page.getByTestId('projects-side')
  await expect(side.getByRole('link', { name: /Sample: bhaji-cam ad/ })).toContainText('Sample')
  expect(posts.filter((p) => p.startsWith('POST /api/me/sample'))).toHaveLength(1)

  const form = page.getByTestId('link-import')
  await expect(form).toContainText('YouTube is not available yet.')
  await form.getByLabel('Or paste a link').fill('https://www.youtube.com/watch?v=abc')
  await form.getByRole('button', { name: 'Import' }).click()
  await expect(form.getByRole('alert')).toContainText('connect your Google account')

  await page.getByLabel('Add to').selectOption('f1')
  await form.getByLabel('Or paste a link').fill('https://www.dropbox.com/s/abc/spring.mp4')
  await form.getByRole('button', { name: 'Import' }).click()
  await expect(page.getByTestId('import-progress')).toContainText('Downloading from Dropbox, 40 MB of 100 MB.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g1-import.png` })
  await expect(page).toHaveURL(/#v\/p9$/)
  expect(posts).toContain('POST /api/imports {"url":"https://www.dropbox.com/s/abc/spring.mp4","project_id":"f1"}')
})
