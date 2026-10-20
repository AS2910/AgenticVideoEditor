import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** D3 in a real browser (API mocked, nothing spent): delete a video from
 *  Home (the confirmation names the Bin), open the Bin from the nav, see who
 *  deleted it and the days left, restore a project with its video and a
 *  video whose project is in the Bin (standalone, said so).
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = Date.now()
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString()
const FLAGS = { flags: ['projects.consistency', 'projects.review', 'projects.reuse'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: [], checklist: [], checklist_hidden: true }

type Item = { kind: string; id: string; name: string; deleted_at: string; deleted_by: string; deleted_by_you: boolean; days_left: number;
  project_id: string | null; project_name: string | null; project_in_bin?: boolean; with_project?: boolean; videos?: number; consent?: boolean }

class World {
  videos = [
    { video_id: 'p1', project_id: 'f1', project_name: 'Diwali 2026', filename: 'bhaji-cam-ad.mp4', duration: 31, created_at: ago(3), edits: 1, state: 'shipped', stage: 'draft' },
  ]
  bin: Item[] = [
    { kind: 'project', id: 'f2', name: 'Spring sale', deleted_at: ago(2), deleted_by: 'local', deleted_by_you: true, days_left: 28, project_id: null, project_name: null, videos: 1 },
    { kind: 'video', id: 'p5', name: 'spring.mp4', deleted_at: ago(2), deleted_by: 'local', deleted_by_you: true, days_left: 28, project_id: 'f2', project_name: 'Spring sale', project_in_bin: true, with_project: true },
    { kind: 'video', id: 'p7', name: 'old-promo.mp4', deleted_at: ago(5), deleted_by: 'local', deleted_by_you: true, days_left: 25, project_id: 'f3', project_name: 'Autumn', project_in_bin: true, with_project: false },
    { kind: 'voice', id: 'V1', name: 'Ashish warm', deleted_at: ago(28), deleted_by: 'local', deleted_by_you: true, days_left: 2, project_id: null, project_name: null, consent: true },
  ]
}

async function serve(page: Page, w: World, posts: string[]) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') posts.push(`${method} ${path}`)
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path.includes('/frames/')) return route.fulfill({ status: 404, body: '' })
    if (path === '/api/bin') return json({ items: w.bin, days: 30 })
    const restore = path.match(/^\/api\/bin\/(\w+)\/(\w+)\/restore$/)
    if (restore && method === 'POST') {
      const [, kind, id] = restore
      if (kind === 'project') {
        w.bin = w.bin.filter((i) => i.id !== id && !(i.kind === 'video' && i.project_id === id && i.with_project))
        return json({ kind, id, videos: ['p5'] })
      }
      w.bin = w.bin.filter((i) => i.id !== id)
      return json({ kind, id, project_id: null, project_name: null, standalone_because: 'Its project Autumn is in the Bin, so it is a standalone video now.' })
    }
    const del = path.match(/^\/api\/videos\/(p\d)$/)
    if (del && method === 'DELETE') {
      const v = w.videos.find((x) => x.video_id === del[1])!
      w.videos = w.videos.filter((x) => x.video_id !== del[1])
      w.bin.unshift({ kind: 'video', id: v.video_id, name: v.filename, deleted_at: new Date().toISOString(), deleted_by: 'local', deleted_by_you: true, days_left: 30, project_id: 'f1', project_name: 'Diwali 2026', project_in_bin: false, with_project: false })
      return route.fulfill({ status: 204, body: '' })
    }
    if (path === '/api/projects') return json({ projects: [{ project_id: 'f1', name: 'Diwali 2026', brief: '', settings: {}, ceiling_usd: null, spent_usd: 0, created_at: ago(9), video_count: w.videos.length }] })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0.12, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: w.videos })
    return json({})
  })
}

test('the Bin: a delete says where it goes, the Bin lists it, Restore puts things back', async ({ page }) => {
  const w = new World()
  const posts: string[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, w, posts)
  await page.goto('/#home')

  // Delete from Home: the confirmation names the Bin and its 30 days.
  await page.getByRole('button', { name: 'More for bhaji-cam-ad.mp4' }).click()
  await page.getByRole('menuitem', { name: 'Delete…' }).click()
  const ask = page.getByRole('group', { name: 'Delete bhaji-cam-ad.mp4?' })
  await expect(ask).toContainText('It goes to the Bin for 30 days')
  await expect(ask).not.toContainText('for good?')
  await ask.getByRole('button', { name: 'Move to the Bin' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Moved bhaji-cam-ad.mp4 to the Bin.' })).toBeVisible()
  await expect.poll(() => posts.includes('DELETE /api/videos/p1'), { timeout: 10_000 }).toBe(true)

  // The Bin, from the nav.
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Bin' }).click()
  await expect(page.getByRole('heading', { name: 'Bin', level: 1 })).toBeVisible()
  const row = page.getByTestId('bin-video:p1')
  await expect(row).toContainText('Deleted by you just now')
  await expect(row).toContainText('Goes back to Diwali 2026')
  await expect(row).toContainText('30 days left')
  await expect(page.getByTestId('bin-voice:V1').getByText('2 days left')).toBeVisible()
  const tip = page.getByRole('status', { name: 'Tip: The Bin' })
  await expect(tip).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d3-bin.png`, fullPage: true })
  await tip.getByRole('button', { name: 'Got it' }).click()

  // A project comes back with the video deleted with it.
  await page.getByRole('button', { name: 'Restore Spring sale' }).click()
  await expect(page.getByTestId('bin-toast')).toContainText('Restored Spring sale with 1 video.')
  await expect(page.getByTestId('bin-project:f2')).toHaveCount(0)
  await expect(page.getByTestId('bin-video:p5')).toHaveCount(0)

  // A video whose project is in the Bin comes back standalone, and says so.
  await page.getByRole('button', { name: 'Restore old-promo.mp4' }).click()
  await expect(page.getByTestId('bin-toast')).toContainText('Its project Autumn is in the Bin, so it is a standalone video now.')
  await expect(page.getByTestId('bin-toast').getByRole('link', { name: 'Open' })).toHaveAttribute('href', '#v/p7')
  expect(posts.filter((p) => p.includes('/restore'))).toEqual(['POST /api/bin/project/f2/restore', 'POST /api/bin/video/p7/restore'])

  // Filters; the empty state.
  await page.getByRole('tab', { name: /Projects · 0/ }).click()
  await expect(page.getByTestId('bin-empty')).toContainText('No projects in the Bin.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d3-bin-restored.png`, fullPage: true })
})
