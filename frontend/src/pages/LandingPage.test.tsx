import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LandingPage } from './LandingPage'
import { AdminWaitlist } from './AdminWaitlist'
import { parseRoute, hrefFor } from '../lib/route'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const PRICING = {
  trial_credits: 5, credit_usd: 1, topup_months: 12, test_mode: true, languages: false, invite_only: true,
  plans: [
    { plan_id: 'starter', name: 'Starter', credits: 15, blurb: 'For one person.', usd: 19, inr: 1599 },
    { plan_id: 'studio', name: 'Studio', credits: 50, blurb: 'For a small team.', usd: 59, inr: 4999 },
    { plan_id: 'agency', name: 'Agency', credits: 160, blurb: 'For agencies.', usd: 179, inr: 14999 },
  ],
  topups: [{ credits: 10, usd: 12, inr: 1008 }, { credits: 25, usd: 30, inr: 2520 }],
}

describe('Launch item 8: the landing page', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('has a #welcome route', () => {
    expect(parseRoute('#welcome')).toEqual({ page: 'welcome' })
    expect(hrefFor({ page: 'welcome' })).toBe('#welcome')
  })

  it('shows what Voltage does, the before and after, the steps, prices from the server, the FAQ and the legal links', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.endsWith('/pricing') ? ok(PRICING) : ok({}))))
    render(<LandingPage />)
    // Run 5 item 9: it leads with ad teams and agencies; one video is the second section.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Change every ad at once.')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByText('For ad teams and agencies')).toBeInTheDocument()
    expect(document.querySelector('main')).toHaveTextContent('Offers, prices, languages.')
    expect(screen.getByTestId('landing-campaign')).toHaveTextContent('Make every offer line say 25% off.')
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent).slice(0, 2)).toEqual(['How it works for a campaign', 'Or change one video'])
    const steps = within(screen.getByRole('heading', { name: 'How it works for a campaign' }).closest('section')!).getAllByRole('heading', { level: 3 })
    expect(steps.map((h) => h.textContent)).toEqual(['Put the campaign in a project', 'Say the change once', 'Review and export them all'])
    // The demo plays the original, then the render.
    const video = screen.getByTestId('demo-video')
    expect(video).toHaveAttribute('src', '/sample-ad.mp4')
    await userEvent.click(screen.getByRole('button', { name: 'After' }))
    expect(screen.getByTestId('demo-video')).toHaveAttribute('src', '/sample-ad-after.mp4')
    expect(screen.getByRole('button', { name: 'After' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(screen.getByTestId('landing-one-video')).getByTestId('landing-demo')).toBeInTheDocument()
    // Prices come from GET /pricing, never the page.
    const plans = await screen.findAllByTestId('plan-card')
    expect(plans.map((p) => within(p).getByRole('heading').textContent)).toEqual(['Starter', 'Studio', 'Agency'])
    expect(plans[0]).toHaveTextContent('$19 a month')
    expect(plans[0]).toHaveTextContent('15 credits a month')
    await userEvent.click(screen.getByRole('button', { name: 'INR' }))
    expect(plans[0]).toHaveTextContent('₹1,599 a month')
    expect(screen.getAllByTestId('topup')[0]).toHaveTextContent('10 credits for ₹1,008')
    expect(screen.getByTestId('landing-pricing')).toHaveTextContent('test mode')
    // Language versions are on request while Phase B is off.
    expect(screen.getByText('On request')).toBeInTheDocument()
    const faq = screen.getByTestId('landing-faq')
    expect(faq).toHaveTextContent('Every new account starts with 5 free credits')
    for (const q of ['What is a credit?', 'Is there a free trial?', 'What counts as a minute?', 'Whose voice can I clone?', 'How do I delete my data?', 'Which languages?']) {
      expect(within(faq).getByText(q)).toBeInTheDocument()
    }
    const policies = screen.getByRole('navigation', { name: 'Policies' })
    expect(within(policies).getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '#terms')
    expect(within(policies).getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '#privacy')
    expect(within(policies).getByRole('link', { name: 'Acceptable use' })).toHaveAttribute('href', '#acceptable-use')
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '#login')
    // Empty slots for real quotes and logos show in development, labelled; nothing invented.
    expect(screen.getAllByTestId('landing-slot').map((s) => s.textContent)).toEqual([
      'Slot: customer quote (empty, development only)', 'Slot: customer logos (empty, development only)'])
    expect(document.body.textContent).not.toMatch(/—/)
  })

  it('requests access: labelled fields, an inline error, then one sentence', async () => {
    const posts: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/pricing')) return ok(PRICING)
      if (url.endsWith('/waitlist')) {
        posts.push(JSON.parse(String(init?.body)))
        return ok({ ok: true, message: 'Thanks. You are on the list, and we will email you when there is a place.' }, 201)
      }
      return ok({})
    }))
    render(<LandingPage />)
    const form = screen.getByRole('form', { name: 'Request access' })
    await userEvent.type(within(form).getByLabelText('Email'), 'nope')
    await userEvent.click(within(form).getByRole('button', { name: 'Request access' }))
    const email = within(form).getByLabelText('Email')
    expect(email).toHaveAttribute('aria-invalid', 'true')
    expect(email).toHaveAccessibleDescription('Enter an email address, like you@example.com.')
    expect(email).toHaveFocus()
    expect(posts).toEqual([])
    await userEvent.clear(email)
    await userEvent.type(email, 'bo@example.com')
    await userEvent.type(within(form).getByLabelText(/Name/), 'Bo')
    await userEvent.type(within(form).getByLabelText(/What do you make/), 'cooking shorts')
    await userEvent.click(within(form).getByRole('button', { name: 'Request access' }))
    expect(await screen.findByTestId('access-done')).toHaveTextContent('You are on the list')
    expect(posts).toEqual([{ email: 'bo@example.com', name: 'Bo', use_case: 'cooking shorts' }])
  })

  it('offers an account instead of the form when invite-only is off', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.endsWith('/pricing') ? ok({ ...PRICING, invite_only: false, languages: true }) : ok({}))))
    render(<LandingPage />)
    await screen.findAllByTestId('plan-card')
    expect(screen.queryByTestId('landing-access')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Make an account' })[0]).toHaveAttribute('href', '#login')
    expect(screen.queryByText('On request')).not.toBeInTheDocument()
  })

  it('says so when the prices cannot be read, and tries again', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.endsWith('/pricing') ? (fail ? ok({ detail: 'Down.' }, 500) : ok(PRICING)) : ok({}))))
    render(<LandingPage />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Down.')
    fail = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findAllByTestId('plan-card')).toHaveLength(3)
  })
})

describe('Launch item 8: the admin waitlist', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists who asked, waiting or invited, and sends an invite', async () => {
    const rows = [
      { id: 2, email: 'cy@example.com', name: 'Cy', use_case: 'travel vlogs', created_at: '2026-10-22T10:00:00+00:00', invited_at: null, invited_by: null, status: 'waiting' },
      { id: 1, email: 'bo@example.com', name: null, use_case: null, created_at: '2026-10-21T10:00:00+00:00', invited_at: '2026-10-22T09:00:00+00:00', invited_by: 'acct:admin', status: 'invited' },
    ]
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/admin/waitlist')) return ok({ rows, invite_only: true })
      if (url.endsWith('/admin/waitlist/2/invite')) return ok({ row: { ...rows[0], status: 'invited', invited_at: '2026-10-23T08:00:00+00:00', invited_by: 'acct:admin' } })
      return ok({})
    }))
    render(<AdminWaitlist card="" />)
    const list = await screen.findAllByTestId('waitlist-row')
    expect(list).toHaveLength(2)
    expect(screen.getByTestId('admin-waitlist')).toHaveTextContent('2 asked · 1 waiting')
    expect(list[0]).toHaveTextContent('Waiting')
    expect(list[1]).toHaveTextContent('Invited')
    expect(list[1]).toHaveTextContent('by acct:admin')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite to cy@example.com' }))
    await waitFor(() => expect(screen.getAllByTestId('waitlist-row')[0]).toHaveTextContent('Invited'))
    expect(calls).toContain('POST /api/admin/waitlist/2/invite')
    expect(screen.getByRole('button', { name: 'Send the invite again to cy@example.com' })).toBeInTheDocument()
  })

  it('Invite to beta posts {beta: true} and the row then says Beta', async () => {
    const row = { id: 3, email: 'eve@example.com', name: null, use_case: null, created_at: '2026-10-22T10:00:00+00:00', invited_at: null, invited_by: null, status: 'waiting' }
    const bodies: (string | undefined)[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/admin/waitlist')) return ok({ rows: [row], invite_only: true })
      if (url.endsWith('/admin/waitlist/3/invite')) { bodies.push(init?.body as string | undefined); return ok({ row: { ...row, status: 'invited', invited_at: '2026-10-24T08:00:00+00:00', invited_by: 'acct:admin', beta: true } }) }
      return ok({})
    }))
    render(<AdminWaitlist card="" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Invite to beta: eve@example.com' }))
    await waitFor(() => expect(screen.getByTestId('waitlist-row')).toHaveTextContent('Beta'))
    expect(bodies).toEqual([JSON.stringify({ beta: true })])
    expect(screen.getByRole('button', { name: 'Send the beta invite again to eve@example.com' })).toBeInTheDocument()
  })
})
