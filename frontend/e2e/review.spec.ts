import { expect, test } from '@playwright/test'
import type { Route } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** C2 in a real browser (API mocked, nothing spent): the reviewer's page
 *  (no account) plays the latest version with the watermark, picks another
 *  version and reads what changed, comments at the playing time, approves;
 *  an expired link says so. Then the editor: Send for review makes a link,
 *  a client's comment is a mark on the scrubber and a row under the
 *  transcript: go to its time, reply, resolve, Do what the client asked.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const MP4 = readFileSync(resolve(process.cwd(), '../backend/app/tutorial/fixture/sample-ad.mp4'))
const AT = '2026-10-20T10:00:00Z'

/** The clip with byte ranges, as the server sends it, so the player can seek. */
function serveClip(route: Route) {
  const range = route.request().headers()['range']
  const m = range?.match(/bytes=(\d+)-(\d*)/)
  if (!m) return route.fulfill({ status: 200, contentType: 'video/mp4', headers: { 'Accept-Ranges': 'bytes' }, body: MP4 })
  const start = Number(m[1]), end = m[2] ? Math.min(Number(m[2]), MP4.length - 1) : MP4.length - 1
  return route.fulfill({ status: 206, contentType: 'video/mp4', body: MP4.subarray(start, end + 1),
    headers: { 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${start}-${end}/${MP4.length}` } })
}

const review = () => ({
  scope: 'video', role: 'reviewer', name: 'Priya', expires_at: '2026-11-20T10:00:00.000Z', title: 'bhaji-cam-ad.mp4',
  files: [{ file_id: 'p1-v5', name: 'bhaji-cam-ad-voltage.mp4', kind: 'video', size: MP4.length, duration: 2.3, label: null, video_id: 'p1' }],
  review: {
    reviewer: 'Priya', allow_download: false,
    videos: [{
      video_id: 'p1', title: 'bhaji-cam-ad.mp4', duration: 2.3, current_version: 5, answer: null, comments: [],
      versions: [
        { version: 5, file_id: 'p1-v5', duration: 2.3, created_at: AT, against: 'v4', changes: ['0:00 now says "Now forty percent off today."'] },
        { version: 4, file_id: 'p1-v4', duration: 2.3, created_at: AT, against: 'v3', changes: ['Added a line at 0:01: "Only at Bhajicam."'] },
        { version: 3, file_id: 'p1-v3', duration: 2.3, created_at: AT, against: 'as shot', changes: [] },
      ],
    }],
  },
})

test('the reviewer: latest version with a watermark, what changed, a comment at its time, Approve; an expired link says so', async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = []
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (path.startsWith('/api/share/gone')) return json({ detail: 'This link has expired. Ask the person who shared it for a new one.' }, 410)
    if (path.includes('/files/')) return serveClip(route)
    if (req.method() === 'POST') {
      const body = JSON.parse(req.postData() ?? '{}')
      posts.push({ path, body })
      if (path.endsWith('/comments')) return json({ comment_id: 7, author: 'Priya', at_s: body.at_s, version: body.version, text: body.text, status: 'open', created_at: AT, replies: [] }, 201)
      if (path.endsWith('/approve')) return json({ video_id: 'p1', answer: { answer: 'approved', by: 'Priya', version: body.version, note: body.note ?? null, at: AT } })
    }
    if (path === '/api/share/tok.sig') return json(review())
    return json({})
  })
  await page.setViewportSize({ width: 1280, height: 1000 })
  await page.goto('/#s/tok.sig')
  await expect(page.getByRole('heading', { name: 'bhaji-cam-ad.mp4' })).toBeVisible()
  await expect(page.getByTestId('share-meta')).toContainText('For Priya · 1 video to review')
  const player = page.getByLabel('bhaji-cam-ad.mp4, version 5')
  await expect(player).toHaveAttribute('src', '/api/share/tok.sig/files/p1-v5')
  await expect(page.getByTestId('watermark')).toHaveText('Review copy · Priya')
  await expect(page.getByRole('link', { name: /Download/ })).toHaveCount(0)
  await expect(page.getByTestId('what-changed')).toContainText('0:00 now says "Now forty percent off today."')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c2-review.png`, fullPage: true })

  // Another version and what changed in it.
  await page.getByTestId('version-picker').getByRole('button', { name: 'v4' }).click()
  await expect(page.getByLabel('bhaji-cam-ad.mp4, version 4')).toHaveAttribute('src', '/api/share/tok.sig/files/p1-v4')
  await expect(page.getByTestId('what-changed')).toContainText('What changed in v4 · against v3')
  await page.getByTestId('version-picker').getByRole('button', { name: 'v5 · latest' }).click()

  // A comment pinned to the playing time.
  const video = page.getByLabel('bhaji-cam-ad.mp4, version 5')
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThan(0)
  await video.evaluate((v: HTMLVideoElement) => { v.currentTime = 1.5 })
  await expect(page.getByTestId('comment-form')).toContainText('Comment at 0:01 in v5')
  await page.getByLabel(/Comment at/).fill('Make the logo bigger here')
  await page.getByRole('button', { name: 'Add comment at 0:01' }).click()
  await expect(page.getByTestId('review-comment')).toContainText('Make the logo bigger here')
  expect(posts[0].path).toBe('/api/share/tok.sig/comments')
  expect(posts[0].body).toMatchObject({ video_id: 'p1', version: 5, text: 'Make the logo bigger here', name: 'Priya' })
  expect(Number(posts[0].body.at_s)).toBeCloseTo(1.5, 1)

  // Approve, last; it says who approved which version.
  const answer = page.getByTestId('review-answer')
  await answer.getByLabel(/Note/).fill('Lovely')
  await answer.getByRole('button', { name: 'Approve v5' }).click()
  await expect(page.getByTestId('answer-said')).toContainText('Priya approved v5')
  expect(posts[1]).toEqual({ path: '/api/share/tok.sig/approve', body: { video_id: 'p1', version: 5, note: 'Lovely', name: 'Priya' } })
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c2-review-answered.png`, fullPage: true })

  // An expired link.
  await page.goto('/#s/gone.sig')
  await page.reload()
  await expect(page.getByTestId('share-refused')).toContainText('This link has expired. Ask the person who shared it for a new one.')
})

// ── the editor ───────────────────────────────────────────────────────────────

const FLAGS = { flags: ['projects.review'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true }
const MEDIA = { kind: 'video', sha256: 's'.repeat(64), duration: 2.3, container: 'mp4' }
const LINE = { text: 'Get thirty percent off today.', start: 0.2, end: 2.0, speaker: 'A' }

test('the editor: Send for review, a comment on the scrubber and in the list, reply, resolve, Do what the client asked', async ({ page }) => {
  const posts: { path: string; body: string }[] = []
  let comment = { comment_id: 7, video_id: 'p1', share_id: 'sh1', author_kind: 'reviewer', author_name: 'Priya', at_s: 1.2, version: 5, text: 'Make the logo bigger',
    status: 'open', replies: [] as { author_kind: string; author_name: string; text: string; at: string }[], created_at: AT, resolved_at: null, resolved_by: null, link_name: 'Priya' }
  let links: unknown[] = []
  const video = () => ({
    video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 2.3, media: MEDIA, created_at: AT, consent_granted_at: AT, stage: 'in_review',
    brief_version: 1, made_with_brief: 1, brief_changed: false,
    transcript: LINE.text.split(' ').map((w, k, ws) => ({ text: w, start: LINE.start + (k * (LINE.end - LINE.start)) / ws.length, end: LINE.start + ((k + 0.9) * (LINE.end - LINE.start)) / ws.length })),
    statements: [LINE], speakers: [{ label: 'A', name: 'Jeevan', voice_id: null }], settings: { autonomy: 'ask', turn_usd: 0.5 },
    plan: null, reading: { opening: 'One speaker, one line.', roles: [] }, suggestions: [], frames: [], edits: [],
    messages: [{ role: 'user', text: 'Hello', kind: 'say', seq: 1 }, { role: 'assistant', text: 'Hi.', kind: 'say', seq: 2 }],
  })
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = req.url()
    const path = new URL(url).pathname
    const method = req.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET') posts.push({ path, body: req.postData() ?? '' })
    if (url.includes('/artifacts/')) return serveClip(route)
    if (url.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (url.endsWith('/me/flags')) return json(FLAGS)
    if (url.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/videos/p1/comments') return json({ comments: [comment], open: comment.status === 'open' ? 1 : 0 })
    if (path === '/api/videos/p1/comments/7/replies') {
      comment = { ...comment, replies: [{ author_kind: 'user', author_name: 'local', text: JSON.parse(req.postData() ?? '{}').text, at: AT }] }
      return json(comment)
    }
    if (path === '/api/videos/p1/comments/7/resolve') { comment = { ...comment, status: JSON.parse(req.postData() ?? '{}').resolved ? 'resolved' : 'open' }; return json(comment) }
    if (path === '/api/videos/p1/review-links' && method === 'POST') {
      const body = JSON.parse(req.postData() ?? '{}')
      const link = { share_id: 'sh2', scope: 'video', target: 'p1', role: 'reviewer', name: body.name ?? null, created_at: AT, expires_at: '2026-11-20T10:00:00.000Z', revoked_at: null, state: 'live', url: 'http://localhost:5173/#s/sh2.sig', data: { allow_download: body.allow_download, email: body.email ?? null } }
      links = [link]
      return json(link, 201)
    }
    if (path === '/api/videos/p1/review-links') return json({ links })
    if (path === '/api/videos/p1/turns' && method === 'POST') return json({ job_id: 'j1', status: 'queued' }, 202)
    if (url.includes('/jobs/j1')) return json({ job_id: 'j1', status: 'running', progress: 0, step: 'Reading', result: null })
    if (url.includes('/events')) return route.fulfill({ status: 404, body: '' })
    if (url.endsWith('/videos/p1')) return json(video())
    if (/\/videos\/p1\/jobs(\?|$)/.test(url)) return json({ jobs: [], turn: null })
    if (url.includes('/renders/latest')) return json({ mode: 'final', current_hash: 'h1', stale: false, in_progress: null, latest: null })
    if (url.includes('/messages')) return json([])
    if (url.endsWith('/arrangement')) return json(null, 404)
    if (/\/videos(\?|$)/.test(url)) return json({ videos: [] })
    if (url.endsWith('/projects')) return json({ projects: [{ project_id: 'f1', name: 'Diwali 2026', brief: '', settings: { autonomy: 'ask', turn_usd: 0.5 }, ceiling_usd: null, spent_usd: 0, created_at: AT, video_count: 1 }] })
    if (url.endsWith('/understanding')) return json({ version: 1, read: null, beats: [], corrections: [], style: null })
    if (url.includes('/usage')) return json({ spent_usd: 0, ceiling_usd: 2, lines: [] })
    if (url.includes('/spend')) return json({ video: { spent_usd: 0.01, ceiling_usd: 2, label: 'This video' }, month: { spent_usd: 1.2, ceiling_usd: 100, label: 'October' }, binding: 'video' })
    if (url.includes('/voices')) return json({ voices: [] })
    if (url.includes('/suggestions')) return json({ suggestions: [] })
    return json({})
  })
  await page.setViewportSize({ width: 1360, height: 950 })
  await page.goto('/#v/p1')

  // The comment: a round mark on the scrubber with its words, and a row under the transcript.
  await expect(page.locator('[data-testid="marker"][data-tone="comment"]')).toHaveAttribute('title', 'Comment from Priya: Make the logo bigger')
  const list = page.getByTestId('review-comments')
  await expect(list).toContainText('1 open')
  await expect(list.getByTestId('comment')).toContainText('Make the logo bigger')
  await expect(page.getByRole('status', { name: 'Tip: Client comments' })).toBeVisible()
  await page.getByRole('status', { name: 'Tip: Client comments' }).getByRole('button', { name: 'Got it' }).click()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c2-editor-comments.png`, fullPage: true })
  await list.getByRole('button', { name: 'Go to 0:01' }).click()
  await expect(page.getByTestId('timecode')).toContainText('0:01')

  // Reply and resolve.
  await list.getByRole('button', { name: 'Reply' }).click()
  await list.getByLabel('Reply to Priya').fill('On it')
  await list.getByRole('button', { name: 'Send reply' }).click()
  await expect(list.getByTestId('comment')).toContainText('You On it')

  // Hand it to Voltage: a normal turn with the comment and its time as the goal.
  await list.getByRole('button', { name: 'Do what the client asked' }).click()
  await expect.poll(() => posts.find((p) => p.path === '/api/videos/p1/turns')?.body ?? '').toContain('Priya asked at 0:01 in v5: \\"Make the logo bigger\\". Do what they asked.')

  await list.getByRole('button', { name: 'Resolve' }).click()
  await expect(list).toContainText('0 open · 1 resolved')
  await expect(page.locator('[data-testid="marker"][data-tone="comment"]')).toHaveCount(0)

  // Send for review from the project menu (also under the transcript): name, download off, the link to copy, listed after.
  await expect(page.getByTestId('send-review-open')).toBeVisible()
  await page.getByTestId('crumb').click()
  await page.getByRole('menuitem', { name: 'Send for review…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Send for review' })
  await dialog.getByLabel(/Reviewer's name/).fill('Priya')
  await expect(dialog.getByRole('checkbox', { name: /Allow download/ })).not.toBeChecked()
  await dialog.getByRole('button', { name: 'Make the link' }).click()
  await expect(dialog.getByRole('textbox', { name: 'Review link' })).toHaveValue('http://localhost:5173/#s/sh2.sig')
  await expect(dialog.getByTestId('review-link')).toContainText('Priya')
  const made = posts.find((p) => p.path === '/api/videos/p1/review-links')
  expect(JSON.parse(made!.body)).toEqual({ name: 'Priya', days: 30, allow_download: false })
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/c2-send-for-review.png` })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})
