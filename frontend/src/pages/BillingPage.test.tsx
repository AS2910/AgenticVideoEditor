import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BillingPage } from './BillingPage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const REPORT = {
  period: 'month', spent_usd: 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14, by_vendor: [],
  by_project: [{ project_id: 'p2', filename: 'bhaji-cam-ad.mp4', turns: 5, voice_characters: 612, spent_usd: 1.07, cap_usd: 2 }, { project_id: 'p1', filename: 'goa-beach.mov', turns: 10, voice_characters: 488, spent_usd: 0.94, cap_usd: 2 }],
}
const SETTINGS = { autonomy: 'ask', turn_usd: 0.5, effort: 'high', ask_before: { ship: false, clone: true, design: false } }

describe('BillingPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says plainly that there is no billing yet, with the real ceilings', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/usage?period=month')) return ok(REPORT)
      if (url.endsWith('/me/settings')) return ok(SETTINGS)
      throw new Error(`unexpected url ${url}`)
    }))
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    expect(screen.getByText('No plan yet')).toBeInTheDocument()
    expect(screen.getByText(/Billing isn't set up in this build/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing on file/)).toBeInTheDocument()
    expect(screen.getByText(/No invoices/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/\[[A-Z0-9/ ]+\]/)
    expect(screen.queryByRole('button', { name: /change plan|update|raise/i })).not.toBeInTheDocument()
    expect(await screen.findByText('$2.06')).toBeInTheDocument()
    expect(screen.getByText('/ $10.00')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Spent against the monthly ceiling' })).toHaveAttribute('aria-valuenow', '21')
    expect(screen.getByText('Highest so far: bhaji-cam-ad.mp4 at $1.07')).toBeInTheDocument()
    expect(await screen.findByText('$0.50')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Change in settings' })).toHaveAttribute('href', '#settings')
    expect(screen.getByRole('link', { name: 'Billing' })).toHaveAttribute('aria-current', 'page')
  })

  it('holds the tiles with dashes when the report is away', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    expect(screen.getByText('No plan yet')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
