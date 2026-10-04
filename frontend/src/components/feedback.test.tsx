/**
 * Feedback and forms (UX-6, R-4): a control that waits says so, an unreadable
 * time cannot be voiced, the send button says what it will do, a negative
 * time never shows.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatPanel } from './ChatPanel'
import { LineDoc } from './LineDoc'
import { CandidateCard } from './CandidateCard'
import { clock } from '../transcript/format'
import type { Candidate, Statement } from '../types'

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
const handlers = () => ({
  onSeek: vi.fn(), onHear: vi.fn(), onKeep: vi.fn(), onAnother: vi.fn(), onAnswer: vi.fn(), onUndo: vi.fn(),
  onRemove: vi.fn(), onPlayTake: vi.fn(), onDismiss: vi.fn(),
})

describe('a control that waits says so', () => {
  it('Keep reads Keeping… and is disabled until the request returns', async () => {
    let finish: () => void = () => {}
    const onKeep = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    render(
      <LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} onKeep={onKeep}
        lines={{ '7.500-9.000': { status: 'ready', takes: [CANDIDATE] } }} />,
    )
    const keep = screen.getByRole('button', { name: 'Keep' })
    await userEvent.click(keep)
    expect(screen.getByRole('button', { name: 'Keeping…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Keeping…' })).toHaveAttribute('aria-busy', 'true')
    finish()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Keep' })).toBeEnabled())
  })

  it('Approve reads Approving… while the approval runs', async () => {
    let finish: () => void = () => {}
    const onApprove = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    render(<CandidateCard candidate={CANDIDATE} onApprove={onApprove} onTryAgain={() => {}} projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(screen.getByRole('button', { name: 'Approving…' })).toBeDisabled()
    finish()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled())
  })
})

describe('an unreadable time cannot be voiced', () => {
  it('marks "Starts at" invalid, explains in a sentence, and disables Hear it', async () => {
    const h = handlers()
    render(<LineDoc statements={STATEMENTS} currentTime={0} {...h} />)
    await userEvent.click(within(screen.getByRole('group', { name: 'Actions for 0:05' })).getByRole('button', { name: 'Add a line after' }))
    const editor = screen.getByTestId('editor')
    await userEvent.type(within(editor).getByRole('textbox', { name: 'Words for the new line' }), 'Welcome to Goa')
    const at = within(editor).getByRole('textbox', { name: 'Starts at' })
    await userEvent.type(at, 'soonish')
    expect(at).toHaveAttribute('aria-invalid', 'true')
    expect(within(editor).getByRole('alert')).toHaveTextContent('A time like 0:04.96')
    expect(within(editor).getByRole('button', { name: 'Hear it' })).toBeDisabled()
    await userEvent.clear(at)
    await userEvent.type(at, '0:06.20')
    expect(at).not.toHaveAttribute('aria-invalid')
    await userEvent.click(within(editor).getByRole('button', { name: 'Hear it' }))
    expect(h.onHear).toHaveBeenCalledWith('add-6.900', expect.objectContaining({ at: 6.2, text: 'Welcome to Goa' }))
  })
})

describe('the send button says what it will do', () => {
  it('is labelled by the caller, and Send by default', () => {
    const { rerender } = render(<ChatPanel messages={[]} canSubmit onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
    rerender(<ChatPanel messages={[]} canSubmit onSubmit={() => {}} sendLabel="Change the plan" />)
    expect(screen.getByRole('button', { name: 'Change the plan' })).toBeInTheDocument()
  })
})

describe('times', () => {
  it('never shows a negative clock', () => {
    expect(clock(-0.004)).toBe('0:00')
    expect(clock(65)).toBe('1:05')
  })
})
