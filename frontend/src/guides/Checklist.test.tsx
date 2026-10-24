import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OnboardingProvider } from './onboarding'
import { Checklist, CHECKLIST, BETA_CHECKLIST } from './Checklist'
import { resetFlags } from '../flags/useFlags'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
function routeFetch(checklist: string[], hidden = false) {
  const puts: Record<string, unknown>[] = []
  const base = { tour: { step: 0, finished: false, skipped: false }, tips: [], checklist, checklist_hidden: hidden }
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') { const b = JSON.parse(init.body as string); puts.push(b); return ok({ ...base, ...b }) }
    return ok(base)
  }))
  return puts
}

describe('Checklist', () => {
  afterEach(() => { vi.unstubAllGlobals(); resetFlags() })

  it('has the five things to do once', () => {
    expect(CHECKLIST.map((i) => i.id)).toEqual(['goal', 'add', 'export', 'save-voice', 'autonomy'])
  })

  it('counts what is done, opens the card, offers Show me on the rest, and hides for good', async () => {
    const puts = routeFetch(['goal', 'autonomy'])
    const onShowMe = vi.fn()
    render(<OnboardingProvider debounceMs={10}><Checklist onShowMe={onShowMe} /></OnboardingProvider>)
    const pill = await screen.findByRole('button', { name: /Get started, 2 of 5/ })
    expect(pill).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(pill)
    const card = screen.getByRole('region', { name: 'Get started' })
    expect(within(card).getByRole('meter', { name: 'Get started progress' })).toHaveAttribute('aria-valuenow', '40')
    expect(within(card).getAllByRole('listitem')).toHaveLength(5)
    expect(within(card).getByText('Send Voltage a goal')).toHaveClass('line-through')
    expect(within(card).getAllByRole('button', { name: /Show me/ })).toHaveLength(3)
    await userEvent.click(within(card).getByRole('button', { name: /Show me →: Export a video/ }))
    expect(onShowMe).toHaveBeenCalledWith('export')
    await userEvent.click(within(card).getByRole('button', { name: 'Hide' }))
    expect(screen.queryByRole('button', { name: /Get started/ })).not.toBeInTheDocument()
    await waitFor(() => expect(puts).toEqual([{ checklist_hidden: true }]))
  })

  it('is gone once everything is done, or when it was hidden', async () => {
    routeFetch(['goal', 'add', 'export', 'save-voice', 'autonomy'])
    const { unmount } = render(<OnboardingProvider><Checklist onShowMe={() => {}} /></OnboardingProvider>)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    unmount()
    vi.unstubAllGlobals()
    routeFetch([], true)
    render(<OnboardingProvider><Checklist onShowMe={() => {}} /></OnboardingProvider>)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('reads 0/5 without a provider', () => {
    render(<Checklist onShowMe={() => {}} />)
    expect(screen.getByRole('button', { name: /Get started, 0 of 5/ })).toBeInTheDocument()
  })

  it('is the welcome checklist in the beta: two more items, opened by link or by the feedback dialog', async () => {
    const base = { tour: { step: 0, finished: false, skipped: false }, tips: [], checklist: ['goal'], checklist_hidden: false }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ok(url.endsWith('/me/flags') ? { flags: ['beta.cohort'] } : base)))
    const opened = vi.fn()
    window.addEventListener('voltage:feedback', opened)
    render(<OnboardingProvider><Checklist onShowMe={() => {}} /></OnboardingProvider>)
    const pill = await screen.findByRole('button', { name: /Welcome to the beta, 1 of 7/ })
    expect(BETA_CHECKLIST.map((i) => i.id)).toEqual(['known-issues', 'feedback'])
    await userEvent.click(pill)
    const card = screen.getByRole('region', { name: 'Welcome to the beta' })
    expect(within(card).getAllByRole('listitem')).toHaveLength(7)
    expect(within(card).getByRole('link', { name: /Open →: Read the known issues/ })).toHaveAttribute('href', '#known-issues')
    await userEvent.click(within(card).getByRole('button', { name: /Open →: Tell us one thing/ }))
    expect(opened).toHaveBeenCalled()
    window.removeEventListener('voltage:feedback', opened)
  })
})
