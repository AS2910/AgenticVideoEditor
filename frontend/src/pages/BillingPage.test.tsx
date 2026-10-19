import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BillingPage } from './BillingPage'
import { unlabelledMoney } from '../lib/money'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const SPEND = { month: { spent_usd: 2.06, ceiling_usd: 10, label: 'October' }, binding: 'month' }

describe('BillingPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('holds the plan, the monthly ceiling, payment and invoices, and nothing per project or video', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/api/spend')) return ok(SPEND)
      throw new Error(`unexpected url ${url}`)
    }))
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    expect(screen.getByText('No plan yet')).toBeInTheDocument()
    expect(screen.getByText(/Billing isn't set up in this build/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing on file/)).toBeInTheDocument()
    expect(screen.getByText(/No invoices/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/\[[A-Z0-9/ ]+\]/)
    expect(screen.queryByRole('button', { name: /change plan|update|raise/i })).not.toBeInTheDocument()
    expect(await screen.findByText('October: $2.06')).toBeInTheDocument()
    expect(screen.getByTestId('monthly-ceiling')).toHaveTextContent('of $10')
    expect(screen.getByRole('meter', { name: 'Spent against the monthly ceiling' })).toHaveAttribute('aria-valuenow', '21')
    // Spend scopes: per-project and per-video numbers live on Usage, not here.
    expect(document.body.textContent).not.toMatch(/Per project|Per turn|Highest so far|\.mp4/)
    expect(screen.getByRole('link', { name: 'See where it went in Usage →' })).toHaveAttribute('href', '#usage')
    expect(screen.getByRole('link', { name: 'Billing' })).toHaveAttribute('aria-current', 'page')
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('holds the figure with an ellipsis when the summary is away', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    expect(screen.getByText('No plan yet')).toBeInTheDocument()
    expect(screen.getAllByText(/…/).length).toBeGreaterThan(0)
  })
})
