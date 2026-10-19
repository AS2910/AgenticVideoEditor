/**
 * What the screen says out loud (UX-6, R-2): the sheets behave as modals,
 * the conversation is a log, state changes sit in live regions, meters and
 * bars carry their values.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConsentSheet } from './ConsentSheet'
import { WhatVoltageMayDo } from './WhatVoltageMayDo'
import { VoltagePane } from './VoltagePane'
import { LineDoc } from './LineDoc'
import type { PlanItem } from '../types'

const item = (over: Partial<PlanItem> = {}): PlanItem => ({
  item_id: 'i1', selection: { start: 7.54, end: 9.02 }, old_text: 'Start a live Bajicam session.',
  new_text: 'Start a live Bhaji Cam session.', speaker: 'A', mix: 'replace', reason: 'Brand name',
  kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null, edit_id: null,
  question: null, error: null, note: null, progress: null, ...over,
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
    render(<WhatVoltageMayDo open value={{ autonomy: 'ask', turn_usd: 0.5, effort: 'high', ceiling_usd: 2 }} onChange={() => {}} onClose={() => {}} />)
    const dialog = screen.getByRole('dialog')
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')).filter((el) => !el.hasAttribute('disabled'))
    const last = focusable[focusable.length - 1]
    last.focus()
    await userEvent.tab()
    // From the last control, Tab lands back inside the sheet, not on the page behind.
    expect(dialog.contains(document.activeElement)).toBe(true)
  })
})

describe('what is announced', () => {
  it('keeps the conversation in a polite log, with who said what', () => {
    render(<VoltagePane messages={[{ role: 'user', text: 'Say it warmer' }, { role: 'assistant', text: 'Done.' }]} state="ready" onSubmit={() => {}} />)
    const log = screen.getByRole('log')
    expect(log).toHaveAttribute('aria-live', 'polite')
    expect(log).toHaveTextContent('You: Say it warmer')
    expect(log).toHaveTextContent('Voltage: Done.')
  })

  it('reads what is happening to a line as status', () => {
    const items = [item({ status: 'working', progress: 'Take 1: fitting it' })]
    render(<LineDoc statements={[{ text: 'Start a live Bajicam session.', start: 7.54, end: 9.02, speaker: 'A' }]} currentTime={0} items={items}
      onSeek={() => {}} onHear={() => {}} onAdd={() => {}} onDiscard={() => {}} onUndo={() => {}} onRemove={() => {}} onHearTake={() => {}} />)
    expect(screen.getByTestId('line-working')).toHaveAttribute('role', 'status')
    expect(screen.getByTestId('line-working')).toHaveTextContent('Take 1: fitting it')
  })

  it('names the transcript with a heading', () => {
    render(<LineDoc statements={[{ text: 'Feed is live.', start: 1, end: 2, speaker: 'B' }]} currentTime={0} onSeek={() => {}} onHear={() => {}} onAdd={() => {}} onDiscard={() => {}} onUndo={() => {}} onRemove={() => {}} onHearTake={() => {}} />)
    expect(screen.getByRole('heading', { name: 'Transcript' })).toBeInTheDocument()
  })
})
