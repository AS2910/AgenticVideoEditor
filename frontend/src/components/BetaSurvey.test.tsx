import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BetaSurveyHost, exportedNow } from './BetaSurvey'
import { resetFlags } from '../flags/useFlags'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => '' }) as Response
const QUESTIONS = [
  { id: 'useful', text: 'How useful was Voltage for this video?', choices: [['very', 'Very useful'], ['somewhat', 'Somewhat useful'], ['not', 'Not useful']] },
  { id: 'almost_stopped', text: 'What almost stopped you?', optional: true },
  { id: 'would_pay', text: 'Would you pay for Voltage?', choices: [['yes', 'Yes'], ['maybe', 'Maybe'], ['no', 'No']] },
]

function serve({ beta = true, due = true } = {}) {
  const calls: { method: string; url: string; body?: string }[] = []
  let shown = false
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ method: init?.method ?? 'GET', url, body: init?.body as string | undefined })
    if (url.endsWith('/me/flags')) return ok({ flags: beta ? ['beta.cohort'] : [] })
    if (url.endsWith('/me/beta-survey') && !init?.method) return ok({ due: due && !shown, questions: QUESTIONS })
    if (url.endsWith('/me/beta-survey/shown')) { shown = true; return ok({ due: false }) }
    if (url.endsWith('/me/beta-survey')) return ok({ said: 'Thank you. That helps us more than you know.' }, 201)
    return ok({})
  }))
  return calls
}

describe('BetaSurveyHost', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags() })

  it('asks once after an export, says it was shown, and sends the three answers', async () => {
    const calls = serve()
    window.location.hash = '#v/p12/export'
    render(<BetaSurveyHost waitMs={1} />)
    const dialog = await screen.findByTestId('beta-survey')
    expect(within(dialog).getByRole('heading', { name: 'Your first export' })).toBeInTheDocument()
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/me/beta-survey/shown') && c.body === JSON.stringify({ video_id: 'p12' }))).toBe(true))
    const send = within(dialog).getByRole('button', { name: 'Send answers' })
    expect(send).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Very useful' }))
    await userEvent.type(within(dialog).getByRole('textbox', { name: /What almost stopped you\?/ }), 'The upload was slow')
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Maybe' }))
    await userEvent.click(send)
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Thank you.')
    const posted = calls.find((c) => c.method === 'POST' && c.url.endsWith('/me/beta-survey'))
    expect(JSON.parse(posted!.body!)).toEqual({ useful: 'very', almost_stopped: 'The upload was slow', would_pay: 'maybe', video_id: 'p12' })
    // Shown once: another export does not bring it back.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    exportedNow()
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId('beta-survey')).not.toBeInTheDocument()
    window.location.hash = ''
  })

  it('never asks anyone outside the beta', async () => {
    const calls = serve({ beta: false })
    render(<BetaSurveyHost waitMs={1} />)
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/me/flags'))).toBe(true))
    exportedNow()
    await new Promise((r) => setTimeout(r, 20))
    expect(calls.some((c) => c.url.includes('beta-survey'))).toBe(false)
    expect(screen.queryByTestId('beta-survey')).not.toBeInTheDocument()
  })

  it('asks again when an export happens, and stays away while not due', async () => {
    const calls = serve({ due: false })
    render(<BetaSurveyHost waitMs={1} />)
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/me/beta-survey')).length).toBe(1))
    exportedNow()
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/me/beta-survey')).length).toBe(2))
    expect(screen.queryByTestId('beta-survey')).not.toBeInTheDocument()
  })
})
