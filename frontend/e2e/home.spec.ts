import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** D4 in a real browser (API mocked, nothing spent): pin a project and a
 *  video to the top of Home's sidebar, sort and filter Recent videos
 *  (Needs attention), the Archived filter, `/` to search, and a spoken word
 *  found by search opening the editor at its time.
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (h: number) => new Date(now - h * 3_600_000).toISOString()
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-home-search'], checklist: [], checklist_hidden: true }

const base = { duration: 31, edits: 0, state: 'new', last_change: 'Nothing changed yet', open_comments: 0, brief_changed: false, out_of_sync: false }
const VIDEOS = [
  { ...base, video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', created_at: ago(50), last_edited_at: ago(1), stage: 'approved' },
  { ...base, video_id: 'p2', project_id: 'f1', project_name: 'Diwali 2026', filename: 'reels-cut.mp4', created_at: ago(10), last_edited_at: ago(9), stage: 'draft', brief_changed: true },
  { ...base, video_id: 'p3', project_id: null, project_name: null, filename: 'alone.mp4', created_at: ago(5), last_edited_at: ago(5), stage: 'in_review', open_comments: 2 },
  { ...base, video_id: 'p4', project_id: 'f9', project_name: 'Old launch', filename: 'launch.mp4', created_at: ago(400), last_edited_at: ago(400), stage: 'exported', project_archived: true },
]
const PROJECT = (id: string, name: string, extra = {}) => ({ project_id: id, name, brief: '', settings: {}, ceiling_usd: null, spent_usd: 0, created_at: ago(60), video_count: 2, ...extra })
const SEARCH = { query: 'offer', total: 2, groups: [
  { project_id: 'f1', project_name: 'Diwali 2026', archived: false, hits: [{ kind: 'transcript', video_id: 'p1', filename: 'bhaji-cam-ad.mp4', at: 3.5, text: 'get thirty percent off this offer today', match: 'offer' }] },
  { project_id: 'f9', project_name: 'Old launch', archived: true, hits: [{ kind: 'brief', text: 'A launch offer for the old range.' }] },
] }

async function serve(page: Page, posts: string[]) {
  let pins: { kind: string; id: string; name: string; pinned_at: string }[] = []
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path}`)
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/search') return json({ ...SEARCH, query: url.searchParams.get('q') })
    if (path === '/api/pins') return json({ pins })
    const pin = path.match(/^\/api\/pins\/(project|video)\/(\w+)$/)
    if (pin) {
      const name = pin[1] === 'project' ? 'Diwali 2026' : VIDEOS.find((v) => v.video_id === pin[2])!.filename
      pins = method === 'PUT' ? [...pins.filter((p) => p.id !== pin[2]), { kind: pin[1], id: pin[2], name, pinned_at: new Date().toISOString() }] : pins.filter((p) => p.id !== pin[2])
      return json({ pinned: method === 'PUT' })
    }
    if (path === '/api/projects') {
      return json({ projects: url.searchParams.get('archived') === 'true' ? [PROJECT('f9', 'Old launch', { archived_at: ago(100) })] : [PROJECT('f1', 'Diwali 2026')] })
    }
    if (path.includes('/spend')) return json({ month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: VIDEOS })
    return json({})
  })
}

test('Home: pins, sort and filter, the Archived filter, and / search jumping to a spoken word', async ({ page }) => {
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, posts)
  await page.goto('/#home')
  const side = page.getByTestId('projects-side')
  const cards = page.getByTestId('video-card')

  // An archived project's video is not on Home.
  await expect(cards).toHaveCount(3)
  await expect(page.getByText('launch.mp4')).toHaveCount(0)

  // Pin a project from the sidebar and a video from its card.
  await side.getByRole('button', { name: 'Pin Diwali 2026' }).click()
  await page.getByRole('button', { name: 'More for alone.mp4' }).click()
  await page.getByRole('menuitem', { name: 'Pin to Home' }).click()
  const pinned = page.getByRole('list', { name: 'Pinned' })
  await expect(pinned.getByRole('link')).toHaveText(['Diwali 2026', 'alone.mp4'])
  expect(posts).toEqual(['PUT /api/pins/project/f1', 'PUT /api/pins/video/p3'])

  // Sort: last edited first by default; by name; filter Needs attention.
  await expect(cards.first()).toContainText('bhaji-cam-ad.mp4')
  await page.getByLabel('Sort videos').selectOption('name')
  await expect(cards.first()).toContainText('alone.mp4')
  await page.getByRole('button', { name: 'Needs attention' }).click()
  await expect(cards).toHaveCount(2)
  await expect(page.getByTestId('recent-videos')).not.toContainText('bhaji-cam-ad.mp4')
  await page.getByRole('button', { name: 'Needs attention' }).click()
  await page.getByLabel('Stage').selectOption('approved')
  await expect(cards).toHaveCount(1)
  await page.getByLabel('Stage').selectOption('all')

  // Archived: the filter shows archived projects.
  await side.getByRole('button', { name: /Archived · 1/ }).click()
  await expect(side.getByRole('link', { name: /Old launch/ })).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d4-home.png`, fullPage: true })

  // `/` focuses search; a spoken word opens the editor at its time.
  await page.locator('body').click({ position: { x: 5, y: 300 } })
  await page.keyboard.press('/')
  await expect(page.getByRole('searchbox')).toBeFocused()
  await page.keyboard.type('offer')
  const results = page.getByTestId('search-results')
  await expect(results.getByTestId('search-group-f9')).toContainText('Archived')
  const said = results.getByTestId('search-hit').filter({ hasText: 'bhaji-cam-ad.mp4' })
  await expect(said).toContainText('Said · 0:03')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d4-search.png`, fullPage: true })
  await said.click()
  await expect(page).toHaveURL(/#v\/p1@3\.5$/)
})
