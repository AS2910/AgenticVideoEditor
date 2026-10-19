/**
 * Feedback and forms (UX-6, R-4): a control that waits says so, an unreadable
 * time cannot be voiced, the send button says what it will do, a negative
 * time never shows.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VoltagePane } from './VoltagePane'
import { LineDoc } from './LineDoc'
import { clock } from '../transcript/format'
import type { Candidate, PlanItem, Statement } from '../types'

const STATEMENTS: Statement[] = [
  { text: 'Hi, I want to buy groceries.', start: 5.0, end: 6.9, speaker: 'A' },
  { text: 'Start a live Bajicam session.', start: 7.5, end: 9.0, speaker: 'B' },
]
const CANDIDATE: Candidate = {
  candidate_id: 'c1',
  plan: { selection: { start: 7.5, end: 9.0 }, new_text: 'Start a live Bhaji Cam session.', voice_profile_id: 'v1' },
  audio: { kind: 'audio', sha256: 'a'.repeat(64), duration: 1.5, container: 'wav' },
  frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 1.5, container: 'mp4' },
  continuity: { voice_match: null, prosody: 0.96, audio_integration: 0.99, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] },
}
const ITEM: PlanItem = {
  item_id: 'i1', selection: { start: 7.5, end: 9.0 }, old_text: 'Start a live Bajicam session.', new_text: 'Start a live Bhaji Cam session.',
  speaker: 'B', mix: 'replace', reason: '', kind: 'planned', enabled: true, status: 'ready', fit: null, candidate: CANDIDATE,
  edit_id: null, question: null, error: null, note: null, progress: null,
}
const handlers = () => ({
  onSeek: vi.fn(), onHear: vi.fn(), onAdd: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(),
  onRemove: vi.fn(), onHearTake: vi.fn(),
})

describe('a control that waits says so', () => {
  it('Add it reads Adding… and is disabled until the request returns', async () => {
    let finish: () => void = () => {}
    const onAdd = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    render(
      <LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} onAdd={onAdd} items={[ITEM]} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add it' }))
    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Adding…' })).toHaveAttribute('aria-busy', 'true')
    finish()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add it' })).toBeEnabled())
  })
})

describe('an unreadable time cannot be voiced', () => {
  it('marks "Starts at" invalid, explains in a sentence, and disables Voice it', async () => {
    const h = handlers()
    render(<LineDoc statements={STATEMENTS} currentTime={0} {...h} />)
    await userEvent.click(within(screen.getByRole('group', { name: 'Actions for 0:05' })).getByRole('button', { name: 'Add a line after' }))
    const editor = screen.getByTestId('editor')
    await userEvent.type(within(editor).getByRole('textbox', { name: 'Words for the new line' }), 'Welcome to Goa')
    const at = within(editor).getByRole('textbox', { name: 'Starts at' })
    await userEvent.type(at, 'soonish')
    expect(at).toHaveAttribute('aria-invalid', 'true')
    expect(within(editor).getByRole('alert')).toHaveTextContent('A time like 0:04.96')
    expect(within(editor).getByRole('button', { name: 'Voice it' })).toBeDisabled()
    await userEvent.clear(at)
    await userEvent.type(at, '0:06.20')
    expect(at).not.toHaveAttribute('aria-invalid')
    await userEvent.click(within(editor).getByRole('button', { name: 'Voice it' }))
    expect(h.onHear).toHaveBeenCalledWith('add-6.900', expect.objectContaining({ at: 6.2, text: 'Welcome to Goa' }))
  })
})

describe('the send button says what it will do', () => {
  it('is labelled by the caller, and Send by default', () => {
    const { rerender } = render(<VoltagePane messages={[]} state="ready" onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
    rerender(<VoltagePane messages={[]} state="ready" onSubmit={() => {}} sendLabel="Change the plan" />)
    expect(screen.getByRole('button', { name: 'Change the plan' })).toBeInTheDocument()
  })
})

describe('times', () => {
  it('never shows a negative clock', () => {
    expect(clock(-0.004)).toBe('0:00')
    expect(clock(65)).toBe('1:05')
  })
})
