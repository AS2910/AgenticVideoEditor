import { expect, test } from '@playwright/test'
import type { Page, Route } from '@playwright/test'

/** G2 in a real browser (API mocked): Settings has Members; the owner sees
 *  people with their spend, changes a role and a limit, invites a Reviewer
 *  by email and copies the link; an invite link shows its workspace and
 *  role and joins on Accept. SHOTS=<dir> saves screenshots. */

const SHOTS = process.env.SHOTS ?? ''
const FLAGS = { flags: ['projects.consistency', 'projects.batch', 'projects.review', 'projects.reuse', 'golive.g2'] }
const ONBOARDING = { tour: { step: 0, finished: true, skipped: true }, tips: ['first-members'], checklist: [], checklist_hidden: true }
const VIEW = { workspace: { workspace_id: 'w1', name: 'My workspace', own: true }, you: { user: 'local', role: 'owner' }, workspaces: [{ workspace_id: 'w1', name: 'My workspace', role: 'owner', own: true }] }
const PRIYA = { member: 'google:p', email: 'priya@agency.com', name: null, role: 'editor', role_word: 'Editor', spend_limit_usd: 20, spent_usd: 4.5, joined_at: '' }

async function serve(page: Page, writes: string[]) {
  let state: Record<string, unknown> = { workspace_id: 'w1', owner: { member: 'local', email: 'ash@agency.com', name: null, role: 'owner', role_word: 'Owner', spent_usd: 12.4 },
    members: [PRIYA], invites: [], roles: [{ role: 'editor', word: 'Editor' }, { role: 'reviewer', word: 'Reviewer' }], sign_in: true }
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const method = req.method()
    const json = (b: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) })
    if (method !== 'GET') writes.push(`${method} ${path} ${req.postData() ?? ''}`.trim())
    if (path.endsWith('/auth/me')) return json({ mode: 'off', user: null })
    if (path.endsWith('/me/flags')) return json(FLAGS)
    if (path.endsWith('/me/onboarding')) return json(ONBOARDING)
    if (path === '/api/workspace') return json(VIEW)
    if (path === '/api/workspace/invites') {
      const invite = { id: 'i1', email: 'dev@client.com', role: 'reviewer', spend_limit_usd: null, created_at: '', expires_at: '2026-11-04T00:00:00Z', state: 'waiting', link: 'http://localhost:5173/#invite/i1.abc' }
      state = { ...state, invites: [invite], invite }
      return json(state, 201)
    }
    if (path.startsWith('/api/workspace/members/') && method === 'PATCH') {
      const body = JSON.parse(req.postData() ?? '{}')
      state = { ...state, members: [{ ...PRIYA, ...body, role_word: body.role === 'reviewer' ? 'Reviewer' : 'Editor' }] }
      return json(state)
    }
    if (path === '/api/workspace/members') return json(state)
    if (path === '/api/invites/i1.abc') return json({ email: 'dev@client.com', role: 'reviewer', role_word: 'Reviewer', workspace_name: 'Ash studio', invited_by: 'ash@agency.com', expires_at: '2026-11-04T00:00:00Z', sign_in: true })
    if (path === '/api/invites/i1.abc/accept') return json({ workspace_id: 'w1', workspace_name: 'Ash studio', role: 'reviewer', role_word: 'Reviewer' })
    if (path.includes('/spend')) return json({ month: { spent_usd: 0, ceiling_usd: 100, label: 'October' }, binding: null })
    return json({})
  })
}

test('G2: members, roles, limits and an invite', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const writes: string[] = []
  await page.setViewportSize({ width: 1280, height: 1000 })
  await serve(page, writes)
  await page.goto('/#billing')
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('link', { name: 'Members' }).click()
  await expect(page).toHaveURL(/#members$/)
  const row = page.getByTestId('member-row')
  await expect(row).toContainText('$4.50 of $20.00 this month')
  await row.getByLabel('Role for priya@agency.com').selectOption('reviewer')
  await expect(page.getByRole('status').last()).toContainText('priya@agency.com is now a Reviewer.')
  await row.getByLabel('Monthly limit for priya@agency.com').fill('35')
  await row.getByLabel('Monthly limit for priya@agency.com').press('Enter')
  await expect(page.getByRole('status').last()).toContainText('Limit set to $35.00 a month.')

  const form = page.getByTestId('invite-form')
  await form.getByLabel('Email').fill('dev@client.com')
  await form.getByRole('radio', { name: 'Reviewer' }).click()
  await form.getByRole('button', { name: 'Send invite' }).click()
  const waiting = page.getByTestId('invites')
  await expect(waiting).toContainText('dev@client.com')
  await waiting.getByRole('button', { name: 'Copy link' }).click()
  await expect(waiting.getByRole('button', { name: 'Copied' })).toBeVisible()
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/g2-members.png`, fullPage: true })
  expect(writes).toContain('POST /api/workspace/invites {"email":"dev@client.com","role":"reviewer","spend_limit_usd":null}')
  expect(writes).toContain('PATCH /api/workspace/members/google%3Ap {"spend_limit_usd":35}')

  await page.goto('/#invite/i1.abc')
  const invite = page.getByTestId('invite')
  await expect(invite).toContainText('ash@agency.com invited dev@client.com as a Reviewer')
  await invite.getByRole('button', { name: 'Accept invite' }).click()
  await expect(page.getByText('You are in Ash studio as a Reviewer.')).toBeVisible()
})
