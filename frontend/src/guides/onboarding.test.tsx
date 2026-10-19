import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OnboardingProvider, useOnboarding } from './onboarding'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const SEEN = { tour: { step: 3, finished: false, skipped: false }, tips: ['first-upload'], checklist: ['goal'], checklist_hidden: false }

type Call = { method: string; body: Record<string, unknown> | undefined }
function routeFetch(initial: unknown = SEEN, failGet = false) {
  const calls: Call[] = []
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    if (!url.endsWith('/me/onboarding')) throw new Error(`unexpected ${method} ${url}`)
    if (method === 'GET') { if (failGet) return { ok: false, status: 500, json: async () => ({ detail: 'down' }), text: async () => '' } as Response; return ok(initial) }
    calls.push({ method, body })
    return ok({ ...SEEN, ...body })
  })
  vi.stubGlobal('fetch', f)
  return calls
}

function Probe() {
  const o = useOnboarding()
  return (
    <div>
      <span data-testid="state">{o.loaded ? 'loaded' : 'loading'} · tips [{o.onboarding.tips.join(',')}] · list [{o.onboarding.checklist.join(',')}] · hidden {String(o.onboarding.checklist_hidden)} · tour {o.onboarding.tour.step}</span>
      <button type="button" onClick={() => o.markTip('first-question')}>tip</button>
      <button type="button" onClick={() => o.markChecklist('add')}>check</button>
      <button type="button" onClick={() => o.hideChecklist()}>hide</button>
      <button type="button" onClick={() => o.setTour({ step: 8, finished: true, skipped: false })}>tour</button>
    </div>
  )
}

describe('OnboardingProvider', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads what was seen once, and saves each change at once, one PUT per burst', async () => {
    const calls = routeFetch()
    render(<OnboardingProvider debounceMs={20}><Probe /></OnboardingProvider>)
    expect(screen.getByTestId('state')).toHaveTextContent('loading')
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('loaded · tips [first-upload] · list [goal] · hidden false · tour 3'))
    // One burst: both marks inside the debounce window.
    fireEvent.click(screen.getByRole('button', { name: 'tip' }))
    fireEvent.click(screen.getByRole('button', { name: 'check' }))
    expect(screen.getByTestId('state')).toHaveTextContent('tips [first-upload,first-question] · list [goal,add]')
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({ method: 'PUT', body: { tips: ['first-upload', 'first-question'], checklist: ['goal', 'add'] } })
    fireEvent.click(screen.getByRole('button', { name: 'hide' }))
    fireEvent.click(screen.getByRole('button', { name: 'tour' }))
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1].body).toEqual({ checklist_hidden: true, tour: { step: 8, finished: true, skipped: false } })
    // The same mark again sends nothing.
    await userEvent.click(screen.getByRole('button', { name: 'tip' }))
    await act(() => new Promise((r) => setTimeout(r, 60)))
    expect(calls).toHaveLength(2)
  })

  it('falls back to nothing seen when the server fails, still remembering locally', async () => {
    const calls = routeFetch(undefined, true)
    render(<OnboardingProvider debounceMs={20}><Probe /></OnboardingProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('loaded · tips [] · list [] · hidden false · tour 0'))
    await userEvent.click(screen.getByRole('button', { name: 'tip' }))
    expect(screen.getByTestId('state')).toHaveTextContent('tips [first-question]')
    await waitFor(() => expect(calls).toHaveLength(1))
  })

  it('keeps a mark made before the answer came', async () => {
    let answer: (v: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => (init?.method === 'PUT' ? Promise.resolve(ok(SEEN)) : new Promise<Response>((r) => { answer = r }))))
    render(<OnboardingProvider debounceMs={20}><Probe /></OnboardingProvider>)
    await userEvent.click(screen.getByRole('button', { name: 'check' }))
    expect(screen.getByTestId('state')).toHaveTextContent('loading · tips [] · list [add]')
    await act(async () => { answer(ok(SEEN)) })
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('loaded · tips [first-upload] · list [goal,add] · hidden false · tour 3'))
  })

  it('is a quiet default without a provider', async () => {
    render(<Probe />)
    expect(screen.getByTestId('state')).toHaveTextContent('loaded · tips [] · list [] · hidden false · tour 0')
    await userEvent.click(screen.getByRole('button', { name: 'tip' }))
    expect(screen.getByTestId('state')).toHaveTextContent('tips []')
  })
})
