import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OnboardingProvider } from './onboarding'
import { Tip } from './Tip'
import { TipQueueProvider, TipSlot } from './TipQueue'
import { TIPS } from './tips'
import { SESSION_KEY } from './tipRules'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
function routeFetch(tips: string[]) {
  const puts: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') { const b = JSON.parse(init.body as string); puts.push(b); return ok({ tour: { step: 0, finished: false, skipped: false }, tips: b.tips ?? tips, checklist: [], checklist_hidden: false }) }
    return ok({ tour: { step: 0, finished: false, skipped: false }, tips, checklist: [], checklist_hidden: false })
  }))
  return puts
}

function Page({ ids, slot = 'pane', paused = false }: { ids: string[]; slot?: 'pane' | 'top' | null; paused?: boolean }) {
  return (
    <OnboardingProvider debounceMs={10}>
      <TipQueueProvider paused={paused}>
        {slot && <div data-testid="slot-host"><TipSlot name={slot} /></div>}
        <div data-testid="page">{ids.map((id) => <Tip key={id} id={id} />)}</div>
      </TipQueueProvider>
    </OnboardingProvider>
  )
}

describe('Tip', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('has its tips, each with a sentence and a Help article', () => {
    expect(TIPS.map((t) => t.id)).toEqual(['first-upload', 'first-silent', 'first-question', 'first-just-do-it', 'first-voice-design', 'first-project-voice', 'first-background', 'first-undo-after-export', 'first-ceiling', 'first-credits', 'first-failed-take', 'first-word-rule', 'first-brief-changed', 'first-project-check', 'first-batch', 'first-language-sync', 'first-board', 'first-review-comment', 'first-bin', 'first-template', 'first-learned', 'first-thumbs', 'first-home-search', 'first-sample', 'first-members', 'first-notifications', 'first-consent-liveness', 'first-withdraw-consent', 'first-batch-export'])
    for (const t of TIPS) { expect(t.text.length).toBeGreaterThan(20); expect(t.slug).toMatch(/^[a-z-]+$/) }
  })

  it('shows one at a time in the slot, in the flow, with Got it and a link into Help', async () => {
    const puts = routeFetch([])
    render(<Page ids={['first-question', 'first-upload']} />)
    const tip = await screen.findByRole('status', { name: 'Tip: First question' })
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByTestId('slot-host')).toContainElement(tip)
    expect(screen.getByTestId('page')).not.toContainElement(tip)
    expect(tip.className).not.toMatch(/\bfixed\b|\babsolute\b|\brise\b/)
    expect(within(tip).getByRole('link', { name: /When Voltage asks you/ })).toHaveAttribute('href', '#help/when-voltage-asks-you')

    await userEvent.click(within(tip).getByRole('button', { name: 'Got it' }))
    // The next in line takes its place: the second of the session.
    expect(await screen.findByRole('status', { name: 'Tip: First video' })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Tip: First question' })).not.toBeInTheDocument()
    await waitFor(() => expect(puts).toEqual([{ tips: ['first-question'] }]))
  })

  it('stops at two a session, and the count lasts across a reload', async () => {
    routeFetch([])
    const first = render(<Page ids={['first-question', 'first-upload', 'first-ceiling']} />)
    await userEvent.click(within(await screen.findByRole('status', { name: 'Tip: First question' })).getByRole('button', { name: 'Got it' }))
    await userEvent.click(within(await screen.findByRole('status', { name: 'Tip: First video' })).getByRole('button', { name: 'Got it' }))
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem(SESSION_KEY)!).shown).toEqual(['first-question', 'first-upload'])
    first.unmount()

    // A reload: the server remembers both as met; the session still has no room.
    routeFetch(['first-question', 'first-upload'])
    render(<Page ids={['first-ceiling', 'first-credits']} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('a new session (30 minutes idle) has room again', async () => {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify({ started: Date.now() - 3 * 3600_000, last: Date.now() - 31 * 60_000, shown: ['a', 'b'] }))
    routeFetch([])
    render(<Page ids={['first-ceiling']} />)
    expect(await screen.findByRole('status', { name: 'Tip: Ceiling reached' })).toBeInTheDocument()
  })

  it('stays away once seen, and waits for the answer before showing', async () => {
    routeFetch(['first-question'])
    render(<Page ids={['first-question']} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('waits while a tour runs, and while there is no slot to show in', async () => {
    routeFetch([])
    const { rerender } = render(<Page ids={['first-question']} paused />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    rerender(<Page ids={['first-question']} slot={null} />)
    await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    rerender(<Page ids={['first-question']} slot="top" />)
    expect(await screen.findByRole('status', { name: 'Tip: First question' })).toBeInTheDocument()
  })

  it('sits in the flow when inline (inside a modal)', () => {
    render(<div data-testid="host"><Tip id="first-consent-liveness" inline /></div>)
    const tip = screen.getByRole('status', { name: 'Tip: Read aloud' })
    expect(screen.getByTestId('host')).toContainElement(tip)
    expect(tip.className).not.toMatch(/\bfixed\b/)
    expect(tip.getAttribute('style')).toBeNull()
  })

  it('renders in place without a queue, and ignores an unknown id', () => {
    render(<><Tip id="first-ceiling" /><Tip id="not-a-tip" /></>)
    expect(screen.getByRole('status', { name: 'Tip: Ceiling reached' })).toBeInTheDocument()
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })
})
