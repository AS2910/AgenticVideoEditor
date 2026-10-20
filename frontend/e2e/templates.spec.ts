import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** D1 in a real browser (API mocked, nothing spent): Save as template from a
 *  project page (with the project voice question), New project from a
 *  starter on Home, and the Templates page: rename, delete (asked first).
 *  SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const now = new Date().toISOString()
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-home-search', 'first-template', 'first-board'], checklist: [], checklist_hidden: true }
const PROJECT = (id: string, name: string) => ({ project_id: id, name, brief: 'Warm and bright.', settings: { autonomy: 'ask' }, ceiling_usd: 20, spent_usd: 0, created_at: now, video_count: 0, brief_version: 1 })
const sum = (extra = {}) => ({ brief: 'Warm and bright.', rules: 3, words: 1, presets: 2, voices: 1, ceiling_usd: 20, settings: {}, ...extra })
const STARTERS = [
  { template_id: 'starter-festive-ad', name: 'Festive ad', starter: true, description: 'A short sale or offer ad for a festival, in several cuts.', summary: sum({ voices: 0, words: 0, presets: 3 }) },
  { template_id: 'starter-product-explainer', name: 'Product explainer', starter: true, description: 'One product, explained plainly.', summary: sum({ voices: 0, words: 0 }) },
  { template_id: 'starter-interview-cleanup', name: 'Interview cleanup', starter: true, description: 'A recorded interview, tidied.', summary: sum({ voices: 0, words: 0, presets: 1 }) },
]

async function serve(page: Page, calls: { method: string; path: string; body: unknown }[]) {
  let mine: Record<string, unknown>[] = []
  let folders = [PROJECT('f1', 'Diwali 2026')]
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const body = req.postData() ? JSON.parse(req.postData()!) : null
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') calls.push({ method, path, body })
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/pins') return json({ pins: [] })
    if (path === '/api/templates') return json({ templates: [...STARTERS, ...mine] })
    if (path === '/api/projects/f1/template') {
      if (!body.voice) return json({ detail: 'Dusk belongs to Diwali 2026.', voices: [{ voice_id: 'MADE1', name: 'Dusk' }] }, 409)
      const t = { template_id: 't1', name: body.name, starter: false, created_at: now, summary: sum() }
      mine = [t]
      return json(t, 201)
    }
    const tpl = path.match(/^\/api\/templates\/(\w+)$/)
    if (tpl && method === 'PATCH') { mine = mine.map((t) => ({ ...t, name: body.name })); return json(mine[0]) }
    if (tpl && method === 'DELETE') { mine = []; return route.fulfill({ status: 204, body: '' }) }
    if (path === '/api/projects' && method === 'POST') {
      const made = PROJECT('f2', body.name)
      folders = [...folders, made]
      return json(made, 201)
    }
    if (path === '/api/projects') return json({ projects: url.searchParams.get('archived') === 'true' ? [] : folders })
    if (path === '/api/projects/f1') return json({ project: PROJECT('f1', 'Diwali 2026'), videos: [], voices: [], files: [], suggestions: [] })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    if (/\/videos$/.test(path)) return json({ videos: [] })
    if (path.endsWith('/rules')) return json({ rules: [], rules_version: 0 })
    if (path.endsWith('/export-presets')) return json({ presets: [], codecs: ['h264'] })
    if (path.endsWith('/events')) return json({ events: [], next: null })
    return json({})
  })
}

test('templates: save one from a project, start a project from a starter, rename and delete', async ({ page }) => {
  const calls: { method: string; path: string; body: unknown }[] = []
  await page.setViewportSize({ width: 1280, height: 900 })
  await serve(page, calls)

  // Save as template from the project page: the project's own voice is asked about first.
  await page.goto('/#p/f1')
  await page.getByRole('button', { name: 'More for this project' }).click()
  await page.getByRole('menuitem', { name: 'Save as template…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Save as template' })
  await expect(dialog.getByLabel('Template name')).toHaveValue('Diwali 2026 template')
  await dialog.getByLabel('Template name').fill('Diwali ads')
  await dialog.getByRole('button', { name: 'Save template' }).click()
  await expect(dialog.getByTestId('voice-question')).toContainText('Dusk, a voice that belongs to Diwali 2026.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d1-voice-question.png` })
  await dialog.getByRole('radio', { name: 'Copy the voice into the template' }).click()
  await dialog.getByRole('button', { name: 'Save template' }).click()
  await expect(dialog.getByTestId('template-saved')).toContainText('Diwali ads.')
  expect(calls.filter((c) => c.path === '/api/projects/f1/template').map((c) => c.body)).toEqual([{ name: 'Diwali ads' }, { name: 'Diwali ads', voice: 'copy' }])
  await dialog.getByRole('button', { name: 'Done' }).click()

  // New project on Home, from a starter.
  await page.goto('/#home')
  await page.getByRole('button', { name: '+ New project' }).click()
  const form = page.getByTestId('new-project')
  await form.getByPlaceholder('Project name').fill('Navratri sale')
  await form.getByLabel('Start from').selectOption('starter-festive-ad')
  await expect(form.getByTestId('start-from-facts')).toContainText('No videos.')
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d1-new-from-template.png` })
  await form.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByTestId('projects-side').getByRole('link', { name: /Navratri sale/ })).toBeVisible()
  expect(calls.find((c) => c.path === '/api/projects' && c.method === 'POST')?.body).toEqual({ name: 'Navratri sale', template_id: 'starter-festive-ad' })

  // The Templates page: rename and delete yours; starters are read-only.
  await page.getByTestId('templates-link').click()
  await expect(page.getByRole('heading', { name: 'Templates', level: 1 })).toBeVisible()
  const row = page.getByTestId('template-t1')
  await expect(row).toContainText('Diwali ads')
  await expect(page.getByTestId('template-starter-festive-ad').getByRole('button', { name: /Delete/ })).toHaveCount(0)
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/d1-templates.png`, fullPage: true })
  await row.getByRole('button', { name: 'Rename Diwali ads' }).click()
  await row.getByLabel('New name').fill('Festival ads')
  await row.getByRole('button', { name: 'Save name' }).click()
  await expect(row).toContainText('Festival ads')
  await row.getByRole('button', { name: 'Delete Festival ads' }).click()
  await page.getByRole('button', { name: 'Delete template' }).click()
  await expect(page.getByTestId('templates-empty')).toBeVisible()
  expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(expect.arrayContaining(['PATCH /api/templates/t1', 'DELETE /api/templates/t1']))
})
