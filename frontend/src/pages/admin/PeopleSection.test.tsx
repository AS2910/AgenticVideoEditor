import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PeopleSection } from './PeopleSection'
import { AuditSection } from './AuditSection'
import { ADMIN_SECTIONS } from './sections'
import type { AdminUser } from '../../api'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const USER: AdminUser = {
  owner: 'google:sam', emails: ['sam@example.com'], kind: 'google', is_admin: false, account: null, suspended: null,
  workspace: { workspace_id: 'w2', name: "Sam's workspace", members: [{ member: 'google:mo', email: 'mo@example.com', name: null, role: 'editor', joined_at: '2026-10-01T00:00:00.000Z', spend_limit_usd: null }] },
  member_of: [],
  spend: { today_usd: 1.5, month_usd: 4, all_time_usd: 9.25, by_vendor: { elevenlabs: 6, anthropic: 3.25 }, by_vendor_month: {} },
  credits: { granted: 10, used: 4, left: 6, lapsed: 0, grants: [{ kind: 'trial', credits: 5, reference: 'Free trial', at: '', expires_at: null, left: 1 }] },
  invoices: [{ id: 3, number: 'VLT-202610-00003', description: 'Top-up', total: 11.8, currency: 'USD', provider: 'stripe', test_mode: true, issued_at: '', refunded: false }],
  jobs: [{ job_id: 'J9', video_id: 'p1', kind: 'voice_line', status: 'failed', error_code: 'vendor', error_text: 'The vendor was down.', created_at: '', finished_at: null, cost_usd: null }],
  errors: [{ id: 1, owner: 'google:mo', source: 'client', message: 'Boom', location: '', at: '' }],
  audit: [],
}

describe('Item 10: People on the admin page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('finds a person, shows their account, and suspends with a reason', async () => {
    const calls: string[] = []
    let user: AdminUser = { ...USER }
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.startsWith('/api/admin/users?')) return ok({ users: [{ owner: 'google:sam', emails: ['sam@example.com'], kind: 'google', seen_as: ['signed in'], suspended: false }] })
      if (url.endsWith('/suspend')) {
        user = { ...user, suspended: { reason: 'Abuse report 4', suspended_by: 'google:ada', suspended_at: '2026-10-23T10:00:00.000Z' } }
      }
      return ok(user)
    }))
    const onFlags = vi.fn()
    render(<PeopleSection card="" onFlags={onFlags} />)
    await userEvent.type(screen.getByLabelText('Email or owner id'), 'sam@')
    await userEvent.click(screen.getByRole('button', { name: 'Find' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Open sam@example.com' }))
    const view = await screen.findByTestId('admin-user')
    expect(within(view).getByTestId('user-workspace')).toHaveTextContent('mo@example.com editor')
    expect(within(view).getByTestId('user-spend')).toHaveTextContent('Today $1.50 · this month $4.00 · all time $9.25')
    expect(within(view).getByTestId('user-spend')).toHaveTextContent('elevenlabs $6.00 · anthropic $3.25')
    expect(within(view).getByTestId('user-credits')).toHaveTextContent('6.00 credits left of 10.00 credits granted')
    expect(within(view).getByTestId('user-jobs')).toHaveTextContent('The vendor was down.')
    expect(within(view).getByTestId('user-errors')).toHaveTextContent('Boom')
    const suspend = within(view).getByRole('form', { name: 'Suspend' })
    expect(within(suspend).getByRole('button', { name: 'Suspend' })).toBeDisabled()
    await userEvent.type(within(suspend).getByLabelText('Why'), 'Abuse report 4')
    await userEvent.click(within(suspend).getByRole('button', { name: 'Suspend' }))
    expect(await within(view).findByTestId('user-suspended')).toHaveTextContent('Suspended')
    expect(calls).toContain('POST /api/admin/users/google%3Asam/suspend {"reason":"Abuse report 4"}')
    expect(within(view).getByRole('form', { name: 'Unsuspend' })).toBeInTheDocument()
    await userEvent.click(within(view).getByRole('button', { name: /Features for this person/ }))
    expect(onFlags).toHaveBeenCalledWith('google:sam')
  })

  it('grants credits and refunds a payment, each with a reason', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.startsWith('/api/admin/users?')) return ok({ users: [{ owner: 'google:sam', emails: ['sam@example.com'], kind: 'google', seen_as: [], suspended: false }] })
      return ok(USER)
    }))
    render(<PeopleSection card="" onFlags={() => undefined} />)
    await userEvent.type(screen.getByLabelText('Email or owner id'), 'sam')
    await userEvent.click(screen.getByRole('button', { name: 'Find' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Open sam@example.com' }))
    const grant = await screen.findByRole('form', { name: 'Grant credits' })
    await userEvent.clear(within(grant).getByLabelText('Credits'))
    await userEvent.type(within(grant).getByLabelText('Credits'), '12')
    await userEvent.type(within(grant).getByLabelText('Why'), 'Beta thank you')
    await userEvent.click(within(grant).getByRole('button', { name: 'Grant credits' }))
    const refund = within(screen.getByTestId('user-invoices')).getByRole('form', { name: 'Refund' })
    await userEvent.type(within(refund).getByLabelText('Why'), 'Charged twice')
    await userEvent.click(within(refund).getByRole('button', { name: 'Refund' }))
    await vi.waitFor(() => expect(calls).toContain('POST /api/admin/users/google%3Asam/refund {"reason":"Charged twice","invoice_id":3}'))
    expect(calls).toContain('POST /api/admin/users/google%3Asam/grant {"credits":12,"reason":"Beta thank you"}')
  })

  it('lists the audit trail newest first and takes a share link down', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.includes('/revoke')) return ok({ share_id: 'shAB', owner: 'google:sam', state: 'revoked' })
      return ok({ entries: [
        { id: 2, at: '2026-10-23T10:00:00.000Z', actor: 'google:ada', action: 'suspend', target: 'google:sam', reason: 'Abuse report 4', details: {} },
        { id: 1, at: '2026-10-23T09:00:00.000Z', actor: 'google:ada', action: 'grant', target: 'google:sam', reason: 'Thanks', details: { credits: 5 } },
      ] })
    }))
    render(<AuditSection card="" />)
    const rows = await screen.findAllByTestId('audit-row')
    expect(rows[0]).toHaveTextContent('Suspended · google:sam · by google:adaAbuse report 4')
    expect(rows[1]).toHaveTextContent('Granted credits · 5 credits')
    await userEvent.type(screen.getByLabelText('Share link'), 'https://v.example/#s/shAB.sig')
    await userEvent.type(screen.getByLabelText('Why'), 'Abuse report 4')
    await userEvent.click(screen.getByRole('button', { name: 'Take the link down' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Link shAB is revoked.')
    expect(calls).toContain('POST /api/admin/shares/shAB/revoke {"reason":"Abuse report 4"}')
  })

  it('has one mount point for other admin sections', () => {
    expect(ADMIN_SECTIONS.map((s) => s.id)).toContain('audit')
  })
})
