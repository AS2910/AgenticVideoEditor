import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AdminPage } from './AdminPage'
import { SideNav } from './Shell'
import { parseRoute, hrefFor } from '../lib/route'
import { resetFlags } from '../flags/useFlags'
import { CLIENT_EVENTS, track, trackInTests } from '../lib/analytics'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const FUNNEL = [['signed_up', 'Signed up', 4], ['first_sign_in', 'Signed in', 4], ['video_uploaded', 'Uploaded a video', 3], ['first_turn', 'Asked Voltage', 2],
  ['take_voiced', 'Got a take', 2], ['take_added', 'Added a take', 1], ['first_export', 'Exported', 1]].map(([step, label, owners]) => ({ step, label, owners, share: (owners as number) / 4 }))
const DATA = {
  funnel: FUNNEL,
  take_acceptance: { voiced: 8, added: 3, rate: 0.375 },
  cost_per_exported_minute: { cost_usd: 1.2, minutes: 3, per_minute: 0.4 },
  vendor_quality: [{ vendor: 'elevenlabs', takes: 8, sim_o: null, sim_o_takes: 0, utmos: null, utmos_takes: 0, measured: false }],
  counts: [{ name: 'take_voiced', source: 'server', count: 8, owners: 2, last: '' }, { name: 'bell.opened', source: 'client', count: 1, owners: 1, last: '' }],
}
const EMPTY = { funnel: FUNNEL.map((s) => ({ ...s, owners: 0, share: null })), take_acceptance: { voiced: 0, added: 0, rate: null },
  cost_per_exported_minute: { cost_usd: 0, minutes: 0, per_minute: null }, vendor_quality: [], counts: [] }

describe('G7: the admin page', () => {
  afterEach(() => { vi.unstubAllGlobals(); trackInTests(false); resetFlags() })

  it('routes #admin', () => {
    expect(parseRoute('#admin')).toEqual({ page: 'admin' })
    expect(hrefFor({ page: 'admin' })).toBe('#admin')
  })

  it('shows the funnel, acceptance, cost per minute, vendor quality as not measured, and counts', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok(DATA)))
    render(<AdminPage me={null} />)
    const steps = await screen.findAllByTestId('funnel-step')
    expect(steps).toHaveLength(7)
    expect(steps[2]).toHaveTextContent('Uploaded a video75% of the step before3')
    expect(screen.getByTestId('admin-acceptance')).toHaveTextContent('38%3 added of 8 voiced')
    expect(screen.getByTestId('admin-cost')).toHaveTextContent('$0.40')
    const vendor = screen.getByTestId('vendor-row')
    expect(vendor).toHaveTextContent('SIM-o not measured yet')
    expect(vendor).toHaveTextContent('UTMOS not measured yet')
    expect(screen.getAllByTestId('count-row')[0]).toHaveTextContent('take_voiced')
  })

  it('says so when there is nothing yet, and offers Try again on an error', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async () => (fail ? ok({ detail: 'Not found' }, 404) : ok(EMPTY))))
    render(<AdminPage me={null} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Nobody has signed up yet.')).toBeInTheDocument()
    expect(screen.getByTestId('admin-acceptance')).toHaveTextContent('No takes yet')
    expect(screen.getByTestId('admin-cost')).toHaveTextContent('Nothing exported yet')
    expect(screen.getByText('No takes voiced yet.')).toBeInTheDocument()
  })

  it('lists Admin in the side nav only for an admin with the flag on', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.includes('/me/flags') ? ok({ flags: ['golive.g7'] }) : ok({ admin: true }))))
    render(<SideNav active="admin" />)
    const nav = screen.getByRole('navigation', { name: 'Settings sections' })
    expect(await within(nav).findByRole('link', { name: 'Admin' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('G7: track()', () => {
  afterEach(() => { vi.unstubAllGlobals(); trackInTests(false); resetFlags() })

  it('posts a listed client event when golive.g7 is on, and nothing when it is off', async () => {
    const posts: string[] = []
    let flags = ['golive.g7']
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/me/flags')) return ok({ flags })
      posts.push(`${url} ${init?.body}`)
      return ok({}, 204)
    }))
    trackInTests(true)
    track('bell.opened', { unread: 2 })
    await waitFor(() => expect(posts).toEqual(['/api/analytics/events {"name":"bell.opened","props":{"unread":2}}']))
    resetFlags()
    flags = []
    track('bin.opened')
    await new Promise((r) => setTimeout(r, 20))
    expect(posts).toHaveLength(1)
    expect(CLIENT_EVENTS).toContain('search.opened')
  })

  it('is silent in unit tests unless turned on, and never throws', async () => {
    const fetcher = vi.fn(async () => { throw new Error('offline') })
    vi.stubGlobal('fetch', fetcher)
    track('bell.opened')
    expect(fetcher).not.toHaveBeenCalled()
    trackInTests(true)
    expect(() => track('bell.opened')).not.toThrow()
  })
})
