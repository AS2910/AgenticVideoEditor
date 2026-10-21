import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackProvider, Thumbs } from './Thumbs'
import { ErrorBoundary } from './ErrorBoundary'
import { resetFlags } from '../flags/useFlags'
import { reportError, resetErrorReports } from '../lib/errors'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

function serve(flags: string[], marks = { take: {}, turn: {} }) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/me/flags')) return ok({ flags })
    calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
    if (init?.method === 'PUT') { const b = JSON.parse(String(init.body)); return ok({ ...b, reason: b.reason ?? '' }) }
    if (url.endsWith('/feedback')) return ok(marks)
    return ok({}, 204)
  }))
  return calls
}

describe('G8: thumbs', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags(); resetErrorReports() })

  it('draws nothing without the flag or outside a provider', async () => {
    serve([])
    const { container } = render(<FeedbackProvider videoId="p1"><Thumbs target="take" targetId="c1" /></FeedbackProvider>)
    await new Promise((r) => setTimeout(r, 20))
    expect(container).toBeEmptyDOMElement()
    render(<Thumbs target="take" targetId="c1" />)
    expect(screen.queryByRole('button', { name: 'Good take' })).toBeNull()
  })

  it('shows the saved vote, takes a reason with Send last, and a second press takes the vote back', async () => {
    const calls = serve(['golive.g8'], { take: { c1: { vote: 'up', reason: '' } }, turn: {} } as never)
    render(<FeedbackProvider videoId="p1"><Thumbs target="take" targetId="c1" /><Thumbs target="turn" targetId="m2" dark /></FeedbackProvider>)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Good take' })).toHaveAttribute('aria-pressed', 'true'))
    await userEvent.click(screen.getByRole('button', { name: 'Not a good take' }))
    const box = await screen.findByRole('textbox', { name: 'What was off with this take? (optional)' })
    await userEvent.type(box, 'Wrong stress')
    const form = box.closest('form')!
    const buttons = form.querySelectorAll('button')
    expect(buttons[buttons.length - 1]).toHaveTextContent('Send')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Thanks. That helps.')
    await userEvent.click(screen.getByRole('button', { name: 'Good reply' }))
    await userEvent.click(screen.getByRole('button', { name: 'Good reply' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Good reply' })).toHaveAttribute('aria-pressed', 'false'))
    expect(calls.filter((c) => c.startsWith('PUT'))).toEqual([
      'PUT /api/videos/p1/feedback {"target":"take","target_id":"c1","vote":"down","reason":""}',
      'PUT /api/videos/p1/feedback {"target":"take","target_id":"c1","vote":"down","reason":"Wrong stress"}',
      'PUT /api/videos/p1/feedback {"target":"turn","target_id":"m2","vote":"up","reason":""}',
      'PUT /api/videos/p1/feedback {"target":"turn","target_id":"m2","vote":null,"reason":""}',
    ])
  })

  it('puts the vote back and says so when it does not save', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/me/flags')) return ok({ flags: ['golive.g8'] })
      if (init?.method === 'PUT') return ok({ detail: 'nope' }, 500)
      return ok({ take: {}, turn: {} })
    }))
    render(<FeedbackProvider videoId="p1"><Thumbs target="take" targetId="c1" /></FeedbackProvider>)
    await userEvent.click(await screen.findByRole('button', { name: 'Good take' }))
    expect(await screen.findByRole('status')).toHaveTextContent('That did not save. Try again.')
    expect(screen.getByRole('button', { name: 'Good take' })).toHaveAttribute('aria-pressed', 'false')
  })
})

describe('G8: error reports', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags(); resetErrorReports() })

  it('sends with the flag on, once per message, at most five a minute', async () => {
    const calls = serve(['golive.g8'])
    reportError({ message: 'a' })
    reportError({ message: 'a' })                                         // the same twice: once
    for (const m of ['b', 'c', 'd', 'e', 'f', 'g']) reportError({ message: m })
    await waitFor(() => expect(calls.filter((c) => c.includes('/api/errors'))).toHaveLength(5))
    expect(calls[0]).toContain('"message":"a"')
  })

  it('sends nothing with the flag off', async () => {
    const calls = serve([])
    reportError({ message: 'x' })
    await new Promise((r) => setTimeout(r, 20))
    expect(calls.filter((c) => c.includes('/api/errors'))).toEqual([])
  })

  it('the boundary shows a plain card with Reload and reports what broke', async () => {
    const calls = serve(['golive.g8'])
    const Broken = () => { throw new Error('Render went wrong') }
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ErrorBoundary><Broken /></ErrorBoundary>)
    expect(screen.getByTestId('error-boundary')).toHaveTextContent('Something broke on this screen')
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    await waitFor(() => expect(calls.some((c) => c.includes('/api/errors') && c.includes('Render went wrong') && c.includes('"kind":"boundary"'))).toBe(true))
  })
})
