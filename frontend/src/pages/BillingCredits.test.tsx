import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BillingPage } from './BillingPage'
import { resetFlags } from '../flags/useFlags'
import { unlabelledMoney } from '../lib/money'
import type { BillingView } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const PLANS = [
  { plan_id: 'starter', name: 'Starter', credits: 15, usd: 19, inr: 1599, blurb: 'For one person.', price: 19, currency: 'USD' as const },
  { plan_id: 'studio', name: 'Studio', credits: 50, usd: 59, inr: 4999, blurb: 'For a small team.', price: 59, currency: 'USD' as const },
]
const VIEW = (over: Partial<BillingView> = {}): BillingView => ({
  account: { owner: 'local', plan: null, country: null, legal_name: '', gstin: '', state_code: null, created_at: '' },
  credits: { granted: 5, used: 1.25, left: 3.75, share: 0.25, minutes: null, grants: [] },
  plan: null, plans: PLANS, topups: [{ credits: 10, price: 12, currency: 'USD' }, { credits: 25, price: 30, currency: 'USD' }],
  provider: { name: 'stripe', label: 'Stripe (test mode)', test_mode: true }, trial_credits: 5, invoices: [],
  states: [{ code: '29', name: 'Karnataka' }, { code: '27', name: 'Maharashtra' }], ...over,
})
const INVOICE = { id: 1, number: 'VLT-202610-00001', provider: 'stripe', checkout_id: 'cs_test_00001', kind: 'topup' as const, description: 'Top-up: 10 credits', currency: 'USD' as const,
  subtotal: 12, cgst: 0, sgst: 0, igst: 0, total: 12, tax_kind: 'export' as const, issued_at: '2026-10-21T00:00:00Z', test_mode: true }

function serve(flags: string[], handle: (url: string, init?: RequestInit) => unknown) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/me/flags')) return ok({ flags })
    if (url.endsWith('/api/spend')) return ok({ month: { spent_usd: 2, ceiling_usd: 10, label: 'October' }, binding: 'month' })
    calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
    const out = handle(url, init)
    return out instanceof Response || (out && typeof out === 'object' && 'ok' in (out as object)) ? out as Response : ok(out)
  }))
  return calls
}

describe('G3: billing', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags() })

  it('shows the trial, credits left, test mode, and no minute figure until one is measured', async () => {
    serve(['golive.g3'], () => VIEW())
    const { container } = render(<BillingPage me={{ mode: 'off', user: null }} />)
    const credits = await screen.findByTestId('credits-card')
    expect(credits).toHaveTextContent('Free trial')
    expect(credits).toHaveTextContent('Test mode')
    expect(screen.getByTestId('credits-left')).toHaveTextContent('3.75 credits')
    expect(credits).not.toHaveTextContent('About')
    expect(screen.queryByText(/Nothing on file/)).toBeNull()          // the plain view is gone with the flag on
    expect(unlabelledMoney(container)).toEqual([])
  })

  it('says about N minutes once measured, and pauses with a sentence when credits run out', async () => {
    serve(['golive.g3'], () => VIEW({ credits: { granted: 5, used: 5.5, left: -0.5, share: 1.1, minutes: 0, grants: [] } }))
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    expect(await screen.findByTestId('credits-out')).toHaveTextContent('Your credits are used up, so paid steps are paused. Top up or pick a plan to carry on.')
    expect(screen.getByTestId('credits-card')).toHaveTextContent('About 0 minutes')
  })

  it('switches plan and tops up through the fake provider, then lists the invoice', async () => {
    let view = VIEW()
    const calls = serve(['golive.g3'], (url, init) => {
      if (url.endsWith('/billing/topup')) { view = VIEW({ credits: { ...view.credits, granted: 15, left: 13.75 }, invoices: [INVOICE], invoice: INVOICE }); return view }
      if (url.endsWith('/billing/plan')) { view = VIEW({ account: { ...view.account, plan: 'studio' }, plan: PLANS[1], invoice: { ...INVOICE, number: 'VLT-2', kind: 'plan' } }); return view }
      if (init?.method === 'PUT') return ok({ detail: 'That GSTIN does not look right. It has 15 characters, like 29ABCDE1234F1Z5.' }, 422)
      return view
    })
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    await userEvent.click(await screen.findByRole('button', { name: '10 credits · $12.00' }))
    expect(await screen.findByTestId('billing-status')).toHaveTextContent('10 credits added. Paid in test mode: no money moved.')
    expect(screen.getByTestId('invoice-row')).toHaveTextContent('VLT-202610-00001')
    expect(within(screen.getByTestId('invoice-row')).getByRole('link', { name: 'View invoice' })).toHaveAttribute('href', '/api/billing/invoices/1')
    await userEvent.click(screen.getByRole('button', { name: 'Switch to Studio' }))
    expect(await screen.findByTestId('billing-status')).toHaveTextContent('You are on Studio. 50 credits added for this month. Paid in test mode: no money moved. Invoice VLT-2.')
    expect(screen.getAllByTestId('plan-row')[1]).toHaveTextContent('Your plan')
    expect(calls).toContain('POST /api/billing/topup {"credits":10}')
    expect(calls).toContain('POST /api/billing/plan {"plan":"studio"}')
    // Billing details: India shows GSTIN and state; a bad GSTIN is the server's sentence.
    await userEvent.selectOptions(screen.getByLabelText('Country'), 'IN')
    await userEvent.type(screen.getByLabelText('GSTIN (optional)'), 'BAD')
    await userEvent.click(screen.getByRole('button', { name: 'Save details' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That GSTIN does not look right.')
  })

  it('says so when billing cannot be read, with Try again', async () => {
    serve(['golive.g3'], () => ok({ detail: 'Not found' }, 404))
    render(<BillingPage me={{ mode: 'off', user: null }} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
