import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MembersPage } from './MembersPage'
import { InvitePage } from './InvitePage'
import { parseRoute, hrefFor } from '../lib/route'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const VIEW = (role = 'owner') => ({ workspace: { workspace_id: 'w1', name: 'My workspace', own: role === 'owner' }, you: { user: 'local', role }, workspaces: [{ workspace_id: 'w1', name: 'My workspace', role: 'owner', own: true }] })
const PAGE = (extra: Record<string, unknown> = {}): Record<string, unknown> => ({ workspace_id: 'w1', owner: { member: 'local', email: 'ash@x.io', name: null, role: 'owner', role_word: 'Owner', spent_usd: 1.2 },
  members: [], invites: [], roles: [{ role: 'editor', word: 'Editor' }, { role: 'reviewer', word: 'Reviewer' }], sign_in: true, ...extra })
const PRIYA = { member: 'google:p', email: 'priya@x.io', name: null, role: 'editor', role_word: 'Editor', spend_limit_usd: 20, spent_usd: 4.5, joined_at: '' }
const INVITE = { id: 'i1', email: 'dev@x.io', role: 'reviewer', spend_limit_usd: null, created_at: '', expires_at: '2026-11-04T00:00:00Z', state: 'waiting', link: 'http://x/#invite/i1.abc' }

describe('G2: Members', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('routes #members and #invite/<token>', () => {
    expect(parseRoute('#members')).toEqual({ page: 'members' })
    expect(parseRoute('#invite/i1.ab-c_d')).toEqual({ page: 'invite', token: 'i1.ab-c_d' })
    expect(hrefFor({ page: 'invite', token: 'i1.x' })).toBe('#invite/i1.x')
  })

  it('lists people with their spend, invites with a role and limit, and shows the waiting invite', async () => {
    const calls: string[] = []
    let page = PAGE({ members: [PRIYA] })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.endsWith('/workspace')) return ok(VIEW())
      if (url.endsWith('/workspace/invites')) { page = { ...page, invites: [INVITE], invite: INVITE }; return ok(page, 201) }
      if (url.includes('/me/flags')) return ok({ flags: ['golive.g2'] })
      return ok(page)
    }))
    render(<MembersPage me={null} />)
    const row = await screen.findByTestId('member-row')
    expect(row).toHaveTextContent('priya@x.io')
    expect(row).toHaveTextContent('$4.50 of $20.00 this month')
    const form = screen.getByTestId('invite-form')
    await userEvent.type(within(form).getByLabelText('Email'), 'dev@x.io')
    await userEvent.click(within(form).getByRole('radio', { name: 'Reviewer' }))
    expect(form).toHaveTextContent('Watches and comments. Changes nothing.')
    const buttons = within(form).getAllByRole('button')
    expect(buttons[buttons.length - 1]).toHaveTextContent('Send invite')        // the next action last
    await userEvent.click(within(form).getByRole('button', { name: 'Send invite' }))
    expect(await screen.findByTestId('invites')).toHaveTextContent('dev@x.io')
    expect(calls).toContain('POST /api/workspace/invites {"email":"dev@x.io","role":"reviewer","spend_limit_usd":null,"project_ids":[]}')
    expect(screen.getAllByRole('status').some((s) => s.textContent === 'Invite sent to dev@x.io.')).toBe(true)
  })

  it('shares chosen projects with a Reviewer at the invite, and changes them later (launch item 1)', async () => {
    const calls: string[] = []
    const RAE = { member: 'google:r', email: 'rae@x.io', name: null, role: 'reviewer', role_word: 'Reviewer', spent_usd: 0, shares: { projects: ['f1'], videos: [] } }
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.endsWith('/workspace')) return ok(VIEW())
      if (url.endsWith('/projects')) return ok({ projects: [{ project_id: 'f1', name: 'Diwali' }, { project_id: 'f2', name: 'Holi' }] })
      if (url.includes('/me/flags')) return ok({ flags: ['golive.g2'] })
      return ok(PAGE({ members: [RAE] }))
    }))
    render(<MembersPage me={null} />)
    expect(await screen.findByTestId('member-sees')).toHaveTextContent('Sees Diwali')
    const form = screen.getByTestId('invite-form')
    await userEvent.type(within(form).getByLabelText('Email'), 'dev@x.io')
    await userEvent.click(within(form).getByRole('radio', { name: 'Reviewer' }))
    await userEvent.click(within(form).getByRole('checkbox', { name: 'Holi' }))
    await userEvent.click(within(form).getByRole('button', { name: 'Send invite' }))
    await waitFor(() => expect(calls).toContain('POST /api/workspace/invites {"email":"dev@x.io","role":"reviewer","spend_limit_usd":null,"project_ids":["f2"]}'))
    await userEvent.click(within(screen.getByTestId('member-row')).getByRole('button', { name: 'Change' }))
    await userEvent.click(within(screen.getByTestId('member-row')).getByRole('checkbox', { name: 'Holi' }))
    await userEvent.click(within(screen.getByTestId('member-row')).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls).toContain('PUT /api/workspace/members/google%3Ar/shares {"project_ids":["f1","f2"]}'))
  })

  it('refuses a bad limit in place, and changes a role', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.endsWith('/workspace')) return ok(VIEW())
      return ok(PAGE({ members: [PRIYA] }))
    }))
    render(<MembersPage me={null} />)
    await screen.findByTestId('member-row')
    await userEvent.type(screen.getByTestId('invite-form').querySelector('input[inputmode="decimal"]') as HTMLInputElement, 'lots')
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.co')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite' }))
    expect(screen.getByRole('alert')).toHaveTextContent('A spend limit is an amount like 20')
    await userEvent.selectOptions(screen.getByLabelText('Role for priya@x.io'), 'reviewer')
    await waitFor(() => expect(calls).toContain('PATCH /api/workspace/members/google%3Ap {"role":"reviewer"}'))
  })

  it('tells an Editor their role instead of the list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(VIEW('editor'))))
    render(<MembersPage me={null} />)
    expect(await screen.findByTestId('members-not-owner')).toHaveTextContent('Everything except members and billing. Only the workspace owner manages members.')
  })

  it('an invite says the workspace and role, then Accept last; a dead one says why', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return ok({ workspace_id: 'w1', workspace_name: 'Ash studio', role: 'editor', role_word: 'Editor' })
      return ok({ email: 'dev@x.io', role: 'editor', role_word: 'Editor', workspace_name: 'Ash studio', invited_by: 'ash@x.io', expires_at: '2026-11-04T00:00:00Z', sign_in: true })
    }))
    const { unmount } = render(<InvitePage token="i1.x" />)
    const card = await screen.findByTestId('invite')
    expect(card).toHaveTextContent('ash@x.io invited dev@x.io as an Editor')
    await userEvent.click(within(card).getByRole('button', { name: 'Accept invite' }))
    expect(await screen.findByText('You are in Ash studio as an Editor.')).toBeInTheDocument()
    unmount()
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'This invite has expired. Ask for a new one.' }, 410)))
    render(<InvitePage token="i1.x" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('This invite has expired. Ask for a new one.')
  })
})
