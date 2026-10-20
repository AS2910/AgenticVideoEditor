import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OnboardingProvider } from './onboarding'
import { Tip } from './Tip'
import { TIPS } from './tips'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
function routeFetch(tips: string[]) {
  const puts: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') { const b = JSON.parse(init.body as string); puts.push(b); return ok({ tour: { step: 0, finished: false, skipped: false }, tips: b.tips ?? tips, checklist: [], checklist_hidden: false }) }
    return ok({ tour: { step: 0, finished: false, skipped: false }, tips, checklist: [], checklist_hidden: false })
  }))
  return puts
}

describe('Tip', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('has its tips, each with a sentence and a Help article', () => {
    expect(TIPS.map((t) => t.id)).toEqual(['first-upload', 'first-silent', 'first-question', 'first-just-do-it', 'first-voice-design', 'first-project-voice', 'first-background', 'first-undo-after-export', 'first-ceiling', 'first-failed-take', 'first-word-rule', 'first-brief-changed', 'first-project-check', 'first-batch', 'first-batch-export'])
    for (const t of TIPS) { expect(t.text.length).toBeGreaterThan(20); expect(t.slug).toMatch(/^[a-z-]+$/) }
  })

  it('shows once, under its control, with Got it and a link into Help', async () => {
    const puts = routeFetch([])
    render(
      <OnboardingProvider debounceMs={10}>
        <button type="button" data-tour="add-it">Add it</button>
        <Tip id="first-question" target="add-it" />
        <Tip id="first-upload" target="nowhere" />
      </OnboardingProvider>,
    )
    const tip = await screen.findByRole('status', { name: 'Tip: First question' })
    expect(tip).toHaveTextContent('Voltage asks only when it cannot decide')
    expect(within(tip).getByRole('link', { name: /When Voltage asks you/ })).toHaveAttribute('href', '#help/when-voltage-asks-you')
    // The one with no control on the page sits at the bottom right.
    const loose = screen.getByRole('status', { name: 'Tip: First video' })
    expect(loose.style.bottom).toBe('16px')
    expect(loose.style.right).toBe('16px')

    await userEvent.click(within(tip).getByRole('button', { name: 'Got it' }))
    expect(screen.queryByRole('status', { name: 'Tip: First question' })).not.toBeInTheDocument()
    await waitFor(() => expect(puts).toEqual([{ tips: ['first-question'] }]))
  })

  it('stays away once seen, and waits for the answer before showing', async () => {
    routeFetch(['first-question'])
    render(<OnboardingProvider><Tip id="first-question" target="add-it" /><span data-testid="x" /></OnboardingProvider>)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 10))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('renders without a provider, and ignores an unknown id', () => {
    render(<><Tip id="first-ceiling" target="spend" /><Tip id="not-a-tip" target="spend" /></>)
    expect(screen.getByRole('status', { name: 'Tip: Ceiling reached' })).toBeInTheDocument()
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })
})
