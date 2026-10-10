/**
 * What the screen says out loud (UX-6, R-2): the sheets behave as modals,
 * the conversation is a log, state changes sit in live regions, meters and
 * bars carry their values.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentSheet } from './ConsentSheet'
import { ShipSheet } from './ShipSheet'
import { ChatPanel } from './ChatPanel'
import { SpendMeter } from './SpendMeter'
import { PlanCard } from './PlanCard'
import type { Plan, PlanItem } from '../types'

const item = (over: Partial<PlanItem> = {}): PlanItem => ({
  item_id: 'i1', selection: { start: 7.54, end: 9.02 }, old_text: 'Start a live Bajicam session.',
  new_text: 'Start a live Bhaji Cam session.', speaker: 'A', mix: 'replace', reason: 'Brand name',
  kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null, edit_id: null,
  question: null, error: null, note: null, progress: null, ...over,
})
const plan = (over: Partial<Plan> = {}): Plan => ({
  plan_id: 'plan1', goal: 'Say Bhaji Cam', summary: 'One change does it.', mode: 'ask', status: 'proposed',
  created_at: '2026-10-02T10:00:00Z', estimate: { items: 1, voice_characters: 31, usd: 0.0093, seconds: 12 },
  findings: [], question: null, spend_usd: 0, log: [], items: [item()], ...over,
})
const handlers = () => ({
  onToggle: vi.fn(), onReword: vi.fn(), onInclude: vi.fn(), onRun: vi.fn(), onAnswer: vi.fn(), onRedo: vi.fn(), onApproveAll: vi.fn(),
})

describe('a sheet is a real modal', () => {
  it('moves focus to its title when it opens, closes on Escape, and gives focus back', async () => {
    const onCancel = vi.fn()
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const { unmount } = render(<ConsentSheet who="the Shopkeeper" onConfirm={() => {}} onCancel={onCancel} />)
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Before I make a voice' }))
    await userEvent.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalledTimes(1)
    unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })

  it('keeps Tab inside the sheet', async () => {
    const shipped = {
      items: [item({ status: 'approved', candidate: null })], held: 0, removed: 0, before: 48.9, after: 48.9,
      download: { url: '/api/x.mp4', filename: 'x.mp4' }, spendUsd: 0,
    }
    render(<ShipSheet shipped={shipped} onVariant={() => {}} onClose={() => {}} />)
    const buttons = screen.getAllByRole('button')
    const last = buttons[buttons.length - 1]
    last.focus()
    await userEvent.tab()
    // From the last control, Tab lands on the first focusable thing in the sheet, not on the page behind.
    const first = screen.getByRole('link', { name: 'Download MP4' })
    expect(document.activeElement).toBe(first)
    await userEvent.tab({ shift: true })
    expect(document.activeElement).toBe(last)
  })
})

describe('what is announced', () => {
  it('keeps the conversation in a polite log, with who said what', () => {
    render(<ChatPanel messages={[{ role: 'user', text: 'Say it warmer' }, { role: 'assistant', text: 'Done.' }]} canSubmit onSubmit={() => {}} />)
    const log = screen.getByRole('log')
    expect(log).toHaveAttribute('aria-live', 'polite')
    expect(log).toHaveTextContent('You: Say it warmer')
    expect(log).toHaveTextContent('Voltage: Done.')
  })

  it('reads the spend as a meter with words, and says when it is near the cap', () => {
    const usage = {
      spent_usd: 1.7, ceiling_usd: 2, voice_characters: 120, voice_characters_ceiling: 2000,
      lines: [{ vendor: 'elevenlabs', what: 'voice', unit: 'chars', units: 120, usd: 1.7, calls: 3 }],
    }
    render(<SpendMeter usage={usage} />)
    const meter = screen.getByRole('meter', { name: 'Spend against the cap' })
    expect(meter).toHaveAttribute('aria-valuenow', '1.7')
    // The meter is a button that opens the breakdown; its name carries the words.
    expect(screen.getByRole('button', { name: /^Spent \$1\.70 of \$2\.00 on this project, near the cap\. Show the breakdown$/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('status')).toHaveTextContent('near the cap')
  })

  it('exposes the plan\'s progress as a progressbar with a value, and narration as status', () => {
    const p = plan({ status: 'running', items: [item({ status: 'working', progress: 'Take 1: fitting it' }), item({ item_id: 'i2', status: 'ready' })] })
    render(<PlanCard plan={p} speakers={[]} voices={[]} projectId="p1" {...handlers()} />)
    const bar = screen.getByRole('progressbar', { name: 'Voicing the plan' })
    expect(bar).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByRole('status')).toHaveTextContent('Take 1: fitting it')
  })

  it('names the plan with a heading', () => {
    render(<PlanCard plan={plan()} speakers={[]} voices={[]} projectId="p1" {...handlers()} />)
    expect(screen.getByRole('heading', { name: 'The plan' })).toBeInTheDocument()
  })
})
