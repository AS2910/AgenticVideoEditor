import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TranscriptDoc } from './TranscriptDoc'

const STATEMENTS = [
  { text: 'Hi, I want to buy groceries.', start: 5.2, end: 6.94, speaker: 'A' },
  { text: 'Start a live Bajicam session.', start: 7.54, end: 9.02, speaker: 'A' },
  { text: 'Sure, sir.', start: 9.1, end: 9.8, speaker: 'B' },
]
const SPEAKERS = [
  { label: 'A', name: 'Customer', voice_id: 'nPczCjzI2devNBz1zQrb' },
  { label: 'B', name: 'Shopkeeper', voice_id: null },
]
const VOICES = [
  { voice_id: 'EXAVITQu4vr4xnSDxMaL', name: 'Sarah', description: '', gender: 'female', accent: null, age: null },
  { voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: '', gender: 'male', accent: null, age: null },
]
const noop = () => {}

const doc = (props: Partial<Parameters<typeof TranscriptDoc>[0]> = {}) =>
  render(<TranscriptDoc statements={STATEMENTS} currentTime={0} onSeek={noop} onEdit={noop} {...props} />)

describe('TranscriptDoc', () => {
  it('lists lines with their times, lighting the one playing', () => {
    doc({ currentTime: 8 })
    expect(screen.getByText('0:05')).toBeInTheDocument()
    expect(screen.getByText('Start a live Bajicam session.').closest('[data-current]'))
      .toHaveAttribute('data-current', 'true')
  })

  it('jumps to a line from its time', async () => {
    const onSeek = vi.fn()
    doc({ onSeek })
    await userEvent.click(screen.getByRole('button', { name: 'Go to 0:07' }))
    expect(onSeek).toHaveBeenCalledWith(STATEMENTS[1])
  })

  it('shows the speaker once per change of speaker', () => {
    doc({ speakers: SPEAKERS })
    expect(screen.getAllByRole('img', { name: 'Customer' })).toHaveLength(1)
    expect(screen.getAllByRole('img', { name: 'Shopkeeper' })).toHaveLength(1)
  })

  it('edits a line in place, in the speaker\'s voice, and previews the change', async () => {
    const onEdit = vi.fn()
    doc({ onEdit, speakers: SPEAKERS, voices: VOICES })
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    expect(screen.getByText(/editing 0:07/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Voice' })).toHaveValue('nPczCjzI2devNBz1zQrb')
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await userEvent.clear(box)
    await userEvent.type(box, 'Start a Bhaji Cam session now.')
    await userEvent.click(screen.getByRole('button', { name: /preview change/i }))
    expect(onEdit).toHaveBeenCalledWith(STATEMENTS[1], {
      text: 'Start a Bhaji Cam session now.', voiceId: 'nPczCjzI2devNBz1zQrb', onLong: 'pause',
    })
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('lets a line choose what happens if it runs long, and remembers it', async () => {
    const onEdit = vi.fn()
    const onLongLinesChange = vi.fn()
    doc({ onEdit, onLongLinesChange })
    await userEvent.click(screen.getByText('Sure, sir.'))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /runs long/i }), 'stretch')
    expect(onLongLinesChange).toHaveBeenCalledWith('stretch')
    await userEvent.type(screen.getByRole('textbox', { name: /new wording/i }), ' Right away.{Enter}')
    expect(onEdit).toHaveBeenCalledWith(STATEMENTS[2], expect.objectContaining({ onLong: 'stretch' }))
  })

  it('asks Voltage for wording and puts a lone suggestion in the box', async () => {
    const onReword = vi.fn(async () => ['Sure, sir — right away.'])
    doc({ onReword })
    await userEvent.click(screen.getByText('Sure, sir.'))
    await userEvent.click(screen.getByRole('button', { name: /ask voltage for wording/i }))
    expect(onReword).toHaveBeenCalledWith(STATEMENTS[2], 'Sure, sir.')
    expect(await screen.findByRole('textbox', { name: /new wording/i })).toHaveValue('Sure, sir — right away.')
  })

  it('offers two tighter wordings to choose from', async () => {
    const onReword = vi.fn(async () => ['Sure, right away.', 'Of course, sir.'])
    doc({ onReword })
    await userEvent.click(screen.getByText('Sure, sir.'))
    await userEvent.click(screen.getByRole('button', { name: /ask voltage for wording/i }))
    const offers = await screen.findByTestId('offers')
    expect(offers).toHaveTextContent('Tighter wordings')
    await userEvent.click(within(offers).getByRole('button', { name: 'Of course, sir.' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Of course, sir.')
    expect(screen.queryByTestId('offers')).not.toBeInTheDocument()
  })

  it('shows how the last take on a line was fitted, and tells the panel what is open', async () => {
    const onEditingChange = vi.fn()
    doc({ onEditingChange, readouts: [{ selection: { start: 9.1, end: 9.8 }, tags: ['ran 0.2 s into the pause', 'picture untouched'] }] })
    await userEvent.click(screen.getByText('Sure, sir.'))
    expect(screen.getByTestId('readout')).toHaveTextContent(/Last take fit by:.*ran 0\.2 s into the pause.*picture untouched/)
    expect(onEditingChange).toHaveBeenLastCalledWith(STATEMENTS[2])
    await userEvent.keyboard('{Escape}')
    expect(onEditingChange).toHaveBeenLastCalledWith(null)
  })

  it('offers "prefer a shorter wording" for a line that runs long', async () => {
    const onEdit = vi.fn()
    doc({ onEdit })
    await userEvent.click(screen.getByText('Sure, sir.'))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /runs long/i }), 'shorten')
    await userEvent.type(screen.getByRole('textbox', { name: /new wording/i }), ' Right away.{Enter}')
    expect(onEdit).toHaveBeenCalledWith(STATEMENTS[2], expect.objectContaining({ onLong: 'shorten' }))
  })

  it('does not preview an unchanged line', async () => {
    doc()
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    expect(screen.getByRole('button', { name: /preview change/i })).toBeDisabled()
  })

  it('cancels with Escape', async () => {
    const onEdit = vi.fn()
    doc({ onEdit })
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(onEdit).not.toHaveBeenCalled()
  })

  it('shows an approved change inline as tracked changes, with Revert', async () => {
    const onRevert = vi.fn()
    doc({
      onRevert,
      revisions: [{ edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' }],
    })
    const line = screen.getByTestId('revision')
    expect(within(line).getByText('Bajicam').tagName).toBe('DEL')
    expect(within(line).getByText('Bhaji Cam').tagName).toBe('INS')
    await userEvent.click(screen.getByRole('button', { name: 'Revert' }))
    expect(onRevert).toHaveBeenCalledWith('e1')
  })

  it('names a layered or added line for what it is', () => {
    doc({ revisions: [{ start: 5.2, end: 6.9, text: 'Thirsty!', mix: 'concatenate' }] })
    expect(screen.getByTestId('revision')).toHaveTextContent('Thirsty! (added after this line)')
  })

  it('marks the line the chat is talking about, and the one being worked on', () => {
    doc({
      selection: { start: 7.6, end: 8.0 },
      pendingLines: [{ selection: { start: 9.1, end: 9.8 }, status: 'needs-you' }],
    })
    expect(screen.getByText('Start a live Bajicam session.').closest('[data-selected]'))
      .toHaveAttribute('data-selected', 'true')
    expect(screen.getByText('Needs you')).toBeInTheDocument()
  })

  it('shows a planned change as tracked changes before it is voiced', () => {
    doc({ pendingLines: [{ selection: { start: 7.54, end: 9.02 }, status: 'planned', text: 'Start a live Bhaji Cam session.' }] })
    const line = screen.getByTestId('revision')
    expect(within(line).getByText('Bhaji Cam').tagName).toBe('INS')
    expect(screen.getByText('Planned')).toBeInTheDocument()
    expect(screen.getByText(/planned changes show inline/i)).toBeInTheDocument()
  })

  it('lights the line Voltage is reading', () => {
    doc({ pendingLines: [{ selection: { start: 7.54, end: 9.02 }, status: 'reading' }] })
    expect(screen.getByText('Reading')).toBeInTheDocument()
    expect(screen.getByText(/voltage is reading/i)).toBeInTheDocument()
  })
})
