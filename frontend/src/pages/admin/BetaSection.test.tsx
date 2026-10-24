import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BetaSection } from './BetaSection'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const PERSON = {
  owner: 'google:sam', emails: ['sam@example.com'], since: '2026-10-28T09:00:00Z', last_active: '2026-10-29T10:00:00Z', exports: 2,
  spend_usd: 1.234, credits_given: 10, feedback: { messages: 1, latest: 'Lovely, but slow.' },
  survey: { useful: 'very', almost_stopped: 'The upload', would_pay: 'maybe', shown_at: '2026-10-29T10:00:00Z', answered_at: '2026-10-29T10:01:00Z' },
  errors: { count: 1, latest: 'Boom' },
}
const VIEW = { people: [PERSON], survey: { shown: 1, answered: 1, useful: { very: 1, somewhat: 0, not: 0 }, would_pay: { yes: 0, maybe: 1, no: 0 } }, credits_each: 10 }

describe('BetaSection', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows each person with activity, spend, feedback, answers and errors, and adds someone', async () => {
    const posts: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/admin/beta/join')) { posts.push(init?.body as string); return ok({ owner: 'acct:7', joined: true, granted: true, credits: 10, emailed: true }) }
      return ok(VIEW)
    }))
    render(<BetaSection card="" />)
    const row = await screen.findByTestId('beta-person')
    expect(row).toHaveTextContent('sam@example.com')
    expect(row).toHaveTextContent('2 exports')
    expect(row).toHaveTextContent('$1.23 spent')
    expect(row).toHaveTextContent('10 credits given')
    expect(row).toHaveTextContent('1 message')
    expect(row).toHaveTextContent('1 error')
    expect(row).toHaveTextContent('Very useful · Maybe pay')
    expect(row).toHaveTextContent('Latest message: Lovely, but slow.')
    expect(screen.getByTestId('beta-answers')).toHaveTextContent('1 of 1 answered')
    const section = screen.getByTestId('admin-beta')
    await userEvent.type(within(section).getByLabelText('Address or owner id'), 'ann@example.com')
    await userEvent.click(within(section).getByRole('button', { name: 'Add to beta' }))
    expect(await within(section).findByRole('status')).toHaveTextContent('acct:7 is in the beta, with 10 credits. The beta email went.')
    expect(posts).toEqual([JSON.stringify({ who: 'ann@example.com', email: true })])
  })

  it('says so when nobody is in the beta', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ ...VIEW, people: [], survey: { shown: 0, answered: 0, useful: {}, would_pay: {} } })))
    render(<BetaSection card="" />)
    await waitFor(() => expect(screen.getByText('Nobody is in the beta yet.')).toBeInTheDocument())
  })
})
