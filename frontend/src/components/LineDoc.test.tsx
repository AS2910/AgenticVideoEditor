import { describe, it, expect, vi } from 'vitest'
import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LineDoc } from './LineDoc'
import { keyOf, addKeyOf } from '../transcript/keys'
import type { Candidate } from '../types'

const STATEMENTS = [
  { text: 'Hi, I want to buy groceries.', start: 5.2, end: 6.94, speaker: 'A' },
  { text: 'Start a live Bajicam session.', start: 7.54, end: 9.02, speaker: 'A' },
  { text: 'Sure, sir.', start: 9.38, end: 9.88, speaker: 'B' },
]
const SPEAKERS = [
  { label: 'A', name: 'the Customer', voice_id: 'nPczCjzI2devNBz1zQrb' },
  { label: 'B', name: 'the Shopkeeper', voice_id: null },
]
const VOICES = [
  { voice_id: 'EXAVITQu4vr4xnSDxMaL', name: 'Sarah', description: '', gender: 'female', accent: null, age: null },
  { voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: '', gender: 'male', accent: null, age: null },
]
const take = (over: Partial<Candidate> = {}): Candidate => ({
  candidate_id: 'c1',
  plan: { selection: { start: 7.54, end: 9.02 }, new_text: 'Start a live Bhaji Cam session.', voice_profile_id: 'nPczCjzI2devNBz1zQrb', mix: 'replace' },
  audio: { kind: 'audio', sha256: 'a'.repeat(64), duration: 1.5, container: 'wav' },
  frames: { kind: 'video', sha256: 'f'.repeat(64), duration: 1.5, container: 'mp4' },
  continuity: { voice_match: null, prosody: 0.96, audio_integration: 0.99, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] },
  fit_notes: ['trimmed 120 ms of pauses'],
  ...over,
})
const handlers = () => ({
  onSeek: vi.fn(), onHear: vi.fn(), onKeep: vi.fn(), onAnother: vi.fn(), onAnswer: vi.fn(), onUndo: vi.fn(),
  onRemove: vi.fn(), onPlayTake: vi.fn(), onDismiss: vi.fn(),
})
const doc = (props: Partial<Parameters<typeof LineDoc>[0]> = {}) => {
  const h = handlers()
  render(<LineDoc statements={STATEMENTS} currentTime={0} speakers={SPEAKERS} voices={VOICES} {...h} {...props} />)
  return h
}
const KEY = keyOf({ start: 7.54, end: 9.02 })

describe('LineDoc: the line is the unit', () => {
  it('lists lines with their times and shows the speaker once per change', () => {
    doc({ currentTime: 8 })
    expect(screen.getByText('0:07')).toBeInTheDocument()
    expect(screen.getByText('Start a live Bajicam session.').closest('[data-current]')).toHaveAttribute('data-current', 'true')
    expect(screen.getAllByRole('img', { name: 'the Customer' })).toHaveLength(1)
  })

  it('offers every action on the line itself', async () => {
    const h = doc()
    const actions = screen.getByRole('group', { name: 'Actions for 0:07' })
    expect(within(actions).getAllByRole('button').map((b) => b.textContent)).toEqual(
      ['Change the words', 'Change the delivery', 'Add a line after', 'Remove', 'Play original'])
    await userEvent.click(within(actions).getByRole('button', { name: 'Remove' }))
    expect(h.onRemove).toHaveBeenCalledWith(STATEMENTS[1])
    await userEvent.click(within(actions).getByRole('button', { name: 'Play original' }))
    expect(h.onSeek).toHaveBeenCalledWith(STATEMENTS[1])
  })

  it('edits a line in place: wording shown as a change, delivery, voice, cost, Hear it', async () => {
    const h = doc({ usdPerChar: 0.0003 })
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    expect(screen.getByText(/editing 0:07/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Voice' })).toHaveValue('nPczCjzI2devNBz1zQrb')
    const box = screen.getByRole('textbox', { name: /new wording/i })
    await userEvent.clear(box)
    await userEvent.type(box, 'Start a live Bhaji Cam session.')
    expect(screen.getByText(/you'd be changing/i)).toHaveTextContent('Bajicam')
    expect(screen.getByText(/31 characters · about 1¢/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Warmer' }))
    await userEvent.click(screen.getByRole('button', { name: 'Hear it' }))
    expect(h.onHear).toHaveBeenCalledWith(KEY, {
      selection: { start: 7.54, end: 9.02 }, text: 'Start a live Bhaji Cam session.', voiceId: 'nPczCjzI2devNBz1zQrb',
      onLong: 'pause', delivery: 'warmer', mix: 'replace',
    })
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
  })

  it('does not hear an unchanged line, and cancels with Escape', async () => {
    const h = doc()
    await userEvent.click(screen.getByText('Sure, sir.'))
    expect(screen.getByRole('button', { name: 'Hear it' })).toBeDisabled()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
    expect(h.onHear).not.toHaveBeenCalled()
  })

  it('adds a line after a line, over the picture by default', async () => {
    const h = doc()
    await userEvent.click(within(screen.getByRole('group', { name: 'Actions for 0:09' })).getByRole('button', { name: 'Add a line after' }))
    expect(screen.getByText(/adding a line after 0:09/i)).toBeInTheDocument()
    const group = screen.getByRole('group', { name: 'Sound meets picture' })
    expect(within(group).getByRole('button', { name: 'Over the picture' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Everything is 30% off today.{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(addKeyOf(STATEMENTS[2]), expect.objectContaining({
      selection: { start: 9.38, end: 9.88 }, text: 'Everything is 30% off today.', mix: 'over',
    }))
  })

  it('can hold the picture instead', async () => {
    const h = doc()
    await userEvent.click(screen.getByRole('button', { name: /add a line here/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Hold the picture' }))
    await userEvent.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Bye!{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(addKeyOf(STATEMENTS[2]), expect.objectContaining({ mix: 'concatenate' }))
  })

  it('shows the take under its line, with a verdict in words, Keep and Another take', async () => {
    const h = doc({ lines: { [KEY]: { status: 'ready', takes: [take()] } } })
    const card = screen.getByTestId('take')
    expect(card).toHaveTextContent("Take 1 · Brian's voice")
    expect(card).toHaveTextContent('Sounds like the Customer, and sits in the room. Trimmed 120 ms of pauses.')
    expect(card).toHaveTextContent('0.96')
    await userEvent.click(within(card).getByRole('button', { name: 'Play take 1 in the video' }))
    expect(h.onPlayTake).toHaveBeenCalled()
    await userEvent.click(within(card).getByRole('button', { name: 'Keep' }))
    expect(h.onKeep).toHaveBeenCalledWith(KEY, expect.objectContaining({ candidate_id: 'c1' }))
    await userEvent.click(within(card).getByRole('button', { name: 'Another take' }))
    expect(h.onAnother).toHaveBeenCalledWith(KEY)
  })

  it('puts two takes side by side as a choice', async () => {
    const second = take({ candidate_id: 'c2', continuity: { voice_match: null, prosody: 0.7, audio_integration: 0.9, lip_sync: null, passed: false, warnings: ['Pitch is -6.3 semitones off the surrounding speech.'], measured: ['prosody'] }, fit_notes: [] })
    const h = doc({ lines: { [KEY]: { status: 'ready', takes: [take(), second] } } })
    const cards = screen.getAllByTestId('take')
    expect(cards).toHaveLength(2)
    expect(cards[1]).toHaveTextContent('Sounds 6 semitones low for the Customer.')
    await userEvent.click(screen.getByRole('button', { name: 'Keep take 1' }))
    expect(h.onKeep).toHaveBeenCalledWith(KEY, expect.objectContaining({ candidate_id: 'c1' }))
    expect(screen.getByRole('button', { name: /neither/i })).toBeInTheDocument()
  })

  it('shows what is happening, a question with the recommended answer first, and an error with Try again', async () => {
    const request = { selection: { start: 7.54, end: 9.02 }, text: 'x', voiceId: null, onLong: 'pause' as const, delivery: null, mix: 'replace' as const }
    const h = doc({ lines: {
      [keyOf({ start: 5.2, end: 6.94 })]: { status: 'working', takes: [], progress: 'Take 1: pitch is 6 semitones off. Trying again (take 2 of 3)' },
      [KEY]: { status: 'needs-you', takes: [], request, question: { type: 'question', question: 'The new line runs 1.1 s long.', text: 'x', mix: 'replace',
        options: [{ label: 'Use a shorter line: “Two kinds.”', fit: null, mix: null, warning: null, text: 'Two kinds.' }, { label: 'Speed it up', fit: 'stretch', mix: null, warning: null }] } },
      [keyOf({ start: 9.38, end: 9.88 })]: { status: 'failed', takes: [], request, error: 'The voice service was busy. Nothing was charged.' },
    } })
    expect(screen.getByTestId('line-working')).toHaveTextContent('Trying again')
    expect(screen.getByText('Voicing…')).toBeInTheDocument()
    const q = screen.getByTestId('line-needs-you')
    expect(within(q).getAllByRole('button')[0]).toHaveTextContent('Use a shorter line')
    await userEvent.click(within(q).getAllByRole('button')[0])
    expect(h.onAnswer).toHaveBeenCalledWith(KEY, expect.objectContaining({ text: 'Two kinds.' }))
    const err = screen.getByTestId('line-error')
    expect(err).toHaveTextContent('busy')
    await userEvent.click(within(err).getByRole('button', { name: 'Try again' }))
    expect(h.onHear).toHaveBeenCalledWith(keyOf({ start: 9.38, end: 9.88 }), request)
  })

  it('shows a kept change inline with Undo, and a removed line struck through', async () => {
    const h = doc({ revisions: [
      { edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' },
      { edit_id: 'e2', start: 9.38, end: 9.88, text: '', mix: 'remove' },
    ] })
    const kept = screen.getByTestId('revision')
    expect(within(kept).getByText('Bhaji Cam').tagName).toBe('INS')
    expect(screen.getByText('Kept')).toBeInTheDocument()
    expect(screen.getByText('Removed')).toBeInTheDocument()
    expect(screen.getByText('Sure, sir.').tagName).toBe('DEL')
    const undos = screen.getAllByRole('button', { name: 'Undo' })
    await userEvent.click(undos[0])
    expect(h.onUndo).toHaveBeenCalledWith('e1')
    await userEvent.click(undos[1])
    expect(h.onUndo).toHaveBeenCalledWith('e2')
  })

  it('shows a planned change and lights the line Voltage is reading', () => {
    doc({ pendingLines: [
      { selection: { start: 7.54, end: 9.02 }, status: 'planned', text: 'Start a live Bhaji Cam session.' },
      { selection: { start: 9.38, end: 9.88 }, status: 'reading' },
    ] })
    expect(within(screen.getByTestId('revision')).getByText('Bhaji Cam').tagName).toBe('INS')
    expect(screen.getByText('Planned')).toBeInTheDocument()
    expect(screen.getByText('Reading')).toBeInTheDocument()
  })

  it('offers tighter wordings, remembers "if it runs long", and tells the panel what is open', async () => {
    const onReword = vi.fn(async () => ['Sure, right away.', 'Of course, sir.'])
    const onLongLinesChange = vi.fn()
    const onEditingChange = vi.fn()
    doc({ onReword, onLongLinesChange, onEditingChange, readouts: [{ selection: { start: 9.38, end: 9.88 }, tags: ['voice at natural speed'] }] })
    await userEvent.click(screen.getByText('Sure, sir.'))
    expect(onEditingChange).toHaveBeenLastCalledWith(STATEMENTS[2])
    expect(screen.getByTestId('readout')).toHaveTextContent('voice at natural speed')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /runs long/i }), 'shorten')
    expect(onLongLinesChange).toHaveBeenCalledWith('shorten')
    await userEvent.click(screen.getByRole('button', { name: /ask voltage for wording/i }))
    const offers = await screen.findByTestId('offers')
    await userEvent.click(within(offers).getByRole('button', { name: 'Of course, sir.' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Of course, sir.')
  })
})

describe('LineDoc: editing starts from where the line stands', () => {
  const request = { selection: { start: 7.54, end: 9.02 }, text: 'Start a Bhaji Cam session now.', voiceId: 'EXAVITQu4vr4xnSDxMaL', onLong: 'shorten' as const, delivery: 'warmer', mix: 'replace' as const }

  it('reopens with the last wording you tried, and the choices you made', async () => {
    doc({ lines: { [KEY]: { status: 'ready', takes: [take()], request } } })
    await userEvent.click(within(screen.getByRole('group', { name: 'Actions for 0:07' })).getByRole('button', { name: 'Change the words' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Start a Bhaji Cam session now.')
    expect(screen.getByRole('combobox', { name: 'Voice' })).toHaveValue('EXAVITQu4vr4xnSDxMaL')
    expect(screen.getByRole('combobox', { name: /runs long/i })).toHaveValue('shorten')
    expect(screen.getByRole('button', { name: 'Warmer' })).toHaveClass(/pillOn/)
    expect(screen.getByRole('button', { name: 'Hear it' })).toBeEnabled()   // it differs from the line as it stands
  })

  it('reopens a kept line with its kept wording, and measures the change from there', async () => {
    doc({ revisions: [{ edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' }] })
    await userEvent.click(within(screen.getByRole('group', { name: 'Actions for 0:07' })).getByRole('button', { name: 'Change the words' }))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    expect(box).toHaveValue('Start a live Bhaji Cam session.')
    expect(screen.getByRole('button', { name: 'Hear it' })).toBeDisabled()
    await userEvent.type(box, ' Now.')
    expect(screen.getByText(/you'd be changing/i)).not.toHaveTextContent('Bajicam')
    expect(within(screen.getByText(/you'd be changing/i)).getByText('Now.').tagName).toBe('INS')
  })

  it('reopens an added line with what you wrote for it', async () => {
    const added = { ...request, mix: 'over' as const, text: 'Everything is 30% off.', delivery: null }
    doc({ lines: { [addKeyOf(STATEMENTS[2])]: { status: 'failed', takes: [], request: added, error: 'busy' } } })
    await userEvent.click(within(screen.getByRole('group', { name: 'Actions for 0:09' })).getByRole('button', { name: 'Add a line after' }))
    expect(screen.getByRole('textbox', { name: /words for the new line/i })).toHaveValue('Everything is 30% off.')
  })
})

describe('LineDoc: a take can go anywhere on the timeline', () => {
  it('shows where a take starts and lets you move it: drag on the bar, or type a time', async () => {
    const onPlacing = vi.fn()
    const onMove = vi.fn()
    const first = doc({ lines: { [KEY]: { status: 'ready', takes: [take()] } }, onPlacing, onMove })
    const place = screen.getByTestId('place')
    expect(place).toHaveTextContent('Starts at 0:07.54')
    await userEvent.click(within(place).getByRole('button', { name: 'Move' }))
    expect(onPlacing).toHaveBeenCalledWith({ id: 'c1', start: 7.54, duration: 1.5 })
    void first
  })

  it('applies the placed start to the take', async () => {
    const onMove = vi.fn()
    const onPlacing = vi.fn()
    doc({ lines: { [KEY]: { status: 'ready', takes: [take()] } }, onMove, onPlacing, placing: { id: 'c1', start: 9.2, duration: 1.5 } })
    const place = screen.getByTestId('place')
    await userEvent.click(within(place).getByRole('button', { name: 'Nudge later' }))
    expect(onPlacing).toHaveBeenCalledWith({ id: 'c1', start: 9.3, duration: 1.5 })
    const field = within(place).getByRole('textbox', { name: 'Starts at' })
    await userEvent.clear(field)
    await userEvent.type(field, '0:10.00')
    expect(onPlacing).toHaveBeenLastCalledWith({ id: 'c1', start: 10, duration: 1.5 })
    await userEvent.click(within(place).getByRole('button', { name: 'Put it here' }))
    expect(onMove).toHaveBeenCalledWith(KEY, expect.objectContaining({ candidate_id: 'c1' }), 9.2)   // the prop's start wins until re-rendered
    expect(onPlacing).toHaveBeenLastCalledWith(null)
  })

  it('moves a kept line too', async () => {
    const onMoveKept = vi.fn()
    doc({ revisions: [{ edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' }],
      onMoveKept, onPlacing: vi.fn(), placing: { id: 'edit-e1', start: 8.0, duration: 1.48 } })
    await userEvent.click(within(screen.getByTestId('place')).getByRole('button', { name: 'Put it here' }))
    expect(onMoveKept).toHaveBeenCalledWith('e1', 8.0)
  })

  it('lets an added line start at a chosen time', async () => {
    const h = doc()
    await userEvent.click(screen.getByRole('button', { name: /add a line here/i }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Starts at' }), '0:03.50')
    await userEvent.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Welcome to Goa.{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(addKeyOf(STATEMENTS[2]), expect.objectContaining({ text: 'Welcome to Goa.', mix: 'over', at: 3.5 }))
  })
})


describe('LineDoc: keyboard (UX-4)', () => {
  it('moves between lines, opens and closes the editor, plays, keeps, undoes and removes from the keys', async () => {
    const user = userEvent.setup()
    const h = doc({
      lines: { [KEY]: { status: 'ready', takes: [take()] } },
      revisions: [{ edit_id: 'e1', start: 9.38, end: 9.88, text: 'Sure, boss.', mix: 'replace' }],
    })
    const row = (i: number) => document.getElementById(`line-${i}`) as HTMLElement
    act(() => row(0).focus())
    expect(screen.getByTestId('keys')).toHaveTextContent('move')
    await user.keyboard('{ArrowDown}')
    expect(row(1)).toHaveFocus()
    await user.keyboard(' ')
    expect(h.onSeek).toHaveBeenCalledWith(STATEMENTS[1])
    await user.keyboard('k')
    expect(h.onKeep).toHaveBeenCalledWith(KEY, expect.objectContaining({ candidate_id: 'c1' }))
    await user.keyboard('{Enter}')
    expect(screen.getByRole('textbox', { name: 'New wording' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
    await waitFor(() => expect(row(1)).toHaveFocus())
    await user.keyboard('{ArrowDown}')
    await user.keyboard('u')
    expect(h.onUndo).toHaveBeenCalledWith('e1')
    await user.keyboard('{ArrowUp}{ArrowUp}')
    expect(row(0)).toHaveFocus()
    await user.keyboard('{Delete}')
    expect(h.onRemove).toHaveBeenCalledWith(STATEMENTS[0])
    await user.keyboard('a')
    expect(screen.getByRole('textbox', { name: 'Words for the new line' })).toBeInTheDocument()
  })

  it('leaves the keys alone while typing in a line', async () => {
    const user = userEvent.setup()
    const h = doc()
    act(() => (document.getElementById('line-1') as HTMLElement).focus())
    await user.keyboard('{Enter}')
    await user.keyboard(' k u')
    expect(h.onKeep).not.toHaveBeenCalled()
    expect(h.onUndo).not.toHaveBeenCalled()
    expect(h.onSeek).not.toHaveBeenCalled()
  })
})


describe('LineDoc: shifting a line of the original speech (UX-1c)', () => {
  it('offers Shift on an untouched line and places it from the control', async () => {
    const user = userEvent.setup()
    const onShift = vi.fn()
    const onPlacing = vi.fn()
    const h = doc({ onShift, onPlacing })
    void h
    const actions = screen.getByRole('group', { name: 'Actions for 0:07' })
    await user.click(within(actions).getByRole('button', { name: 'Shift to a time…' }))
    expect(onPlacing).toHaveBeenCalledWith({ id: `shift-${KEY}`, start: 7.54, duration: expect.closeTo(1.48, 2) })
  })

  it('shows the control while placing, and "Put it here" shifts the line', async () => {
    const user = userEvent.setup()
    const onShift = vi.fn()
    doc({ onShift, onPlacing: vi.fn(), placing: { id: `shift-${KEY}`, start: 12.3, duration: 1.48 } })
    await user.click(screen.getByRole('button', { name: 'Put it here' }))
    expect(onShift).toHaveBeenCalledWith(STATEMENTS[1], 12.3)
  })

  it('shows a moved line where it was, and as its own row where it now plays', () => {
    doc({
      onMoveKept: vi.fn(),
      onShift: vi.fn(),
      onPlacing: vi.fn(),
      revisions: [
        { edit_id: 'e1', start: 7.54, end: 9.02, text: '', mix: 'remove', partner: 'e2' },
        { edit_id: 'e2', start: 12.3, end: 13.78, text: 'Start a live Bajicam session.', mix: 'layer', partner: 'e1' },
      ],
    })
    // Where it was: struck through, with where it went and Undo.
    expect(screen.getByText(/Moved to 0:12\.30/)).toBeInTheDocument()
    const texts = screen.getAllByText('Start a live Bajicam session.')
    expect(texts.map((t) => t.tagName)).toEqual(['DEL', 'SPAN'])
    // Where it plays now: its own row, last in time order, with Move and a grip.
    const rows = screen.getAllByRole('listitem', { name: /line at/i }).map((r) => r.getAttribute('aria-label'))
    expect(rows).toEqual(['Line at 0:05, the Customer', 'Line at 0:07, the Customer', 'Line at 0:09, the Shopkeeper', 'Moved line at 0:12, the Customer'])
    expect(screen.getByText(/Moved from 0:07, as spoken/)).toBeInTheDocument()
    expect(screen.getByText('Starts at 0:12.30')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /move the line at 0:12/i })).toBeInTheDocument()
    // The line it landed on is left alone.
    expect(screen.queryByText('Kept')).not.toBeInTheDocument()
  })

  it('drags a row down the transcript: the drop shows the time, and the line lands where the row above ends', async () => {
    const onShift = vi.fn()
    const onPlacing = vi.fn()
    doc({ onShift, onPlacing })
    // jsdom has no layout: give each row a box, top to bottom.
    const rowsEls = screen.getAllByRole('listitem', { name: /line at/i })
    rowsEls.forEach((el, k) => {
      el.getBoundingClientRect = () => ({ top: k * 100, height: 100, bottom: k * 100 + 100, left: 0, right: 500, width: 500, x: 0, y: k * 100, toJSON: () => ({}) })
    })
    const grip = screen.getByRole('button', { name: /move the line at 0:05/i })
    fireEvent.pointerDown(grip, { clientY: 50, pointerId: 1 })
    expect(onPlacing).toHaveBeenCalledWith({ id: KEY0, start: 5.2, duration: expect.closeTo(1.74, 2) })
    // Below the third row's midpoint: it would start where that row ends.
    fireEvent.pointerMove(window, { clientY: 280 })
    expect(await screen.findByTestId('drop-line')).toHaveTextContent('Starts at 0:09.88')
    expect(onPlacing).toHaveBeenLastCalledWith({ id: KEY0, start: 9.88, duration: expect.closeTo(1.74, 2) })
    fireEvent.pointerUp(window)
    expect(onShift).toHaveBeenCalledWith(STATEMENTS[0], 9.88)
    expect(onPlacing).toHaveBeenLastCalledWith(null)
    expect(screen.queryByTestId('drop-line')).not.toBeInTheDocument()
  })
})
const KEY0 = keyOf({ start: 5.2, end: 6.94 })

describe('LineDoc: the grip on every row, and moving without dragging (UX-7e)', () => {
  it('nudges on the bar from the grip with the arrow keys: a tenth, or a second with Shift; Escape lets go', () => {
    const onPlacing = vi.fn()
    doc({ onShift: vi.fn(), onPlacing })
    const grip = screen.getByRole('button', { name: /move the line at 0:07/i })
    fireEvent.keyDown(grip, { key: 'ArrowUp' })
    expect(onPlacing).toHaveBeenLastCalledWith({ id: `shift-${KEY}`, start: 7.44, duration: expect.closeTo(1.48, 2) })
    fireEvent.keyDown(grip, { key: 'ArrowDown', shiftKey: true })
    expect(onPlacing).toHaveBeenLastCalledWith({ id: `shift-${KEY}`, start: 8.54, duration: expect.closeTo(1.48, 2) })
  })

  it('continues a nudge from where the bar already is, and Escape lets go', () => {
    const onPlacing = vi.fn()
    doc({ onShift: vi.fn(), onPlacing, placing: { id: `shift-${KEY}`, start: 12.3, duration: 1.48 } })
    const grip = screen.getByRole('button', { name: /move the line at 0:07/i })
    fireEvent.keyDown(grip, { key: 'ArrowDown' })
    expect(onPlacing).toHaveBeenLastCalledWith({ id: `shift-${KEY}`, start: 12.4, duration: expect.closeTo(1.48, 2) })
    fireEvent.keyDown(grip, { key: 'Escape' })
    expect(onPlacing).toHaveBeenLastCalledWith(null)
  })

  it('moves a line up or down from its menu: it lands where the row above the gap ends', async () => {
    const user = userEvent.setup()
    const onShift = vi.fn()
    doc({ onShift, onPlacing: vi.fn() })
    // The second line, up: before the first, at 0.
    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:07' })).getByRole('button', { name: 'Move up' }))
    expect(onShift).toHaveBeenLastCalledWith(STATEMENTS[1], 0)
    // The first line, down: where the second ends.
    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:05' })).getByRole('button', { name: 'Move down' }))
    expect(onShift).toHaveBeenLastCalledWith(STATEMENTS[0], 9.02)
    // The first line has nothing above it; the last has nothing below.
    expect(within(screen.getByRole('group', { name: 'Actions for 0:05' })).queryByRole('button', { name: 'Move up' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Actions for 0:09' })).queryByRole('button', { name: 'Move down' })).not.toBeInTheDocument()
  })

  it('gives a kept line a grip that moves it with its take', () => {
    const onMoveKept = vi.fn()
    const onPlacing = vi.fn()
    doc({ onMoveKept, onPlacing, onShift: vi.fn(), revisions: [{ edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' }] })
    const grip = screen.getByRole('button', { name: /move the line at 0:07/i })
    fireEvent.keyDown(grip, { key: 'ArrowDown' })
    expect(onPlacing).toHaveBeenLastCalledWith({ id: 'edit-e1', start: 7.64, duration: expect.closeTo(1.48, 2) })
  })
})
