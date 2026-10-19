import { describe, it, expect, vi } from 'vitest'
import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LineDoc } from './LineDoc'
import { keyOf, addKeyOf } from '../transcript/keys'
import type { Candidate, PlanItem } from '../types'

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
/** The plan's change to the second line, with its take ready. */
const item = (over: Partial<PlanItem> = {}): PlanItem => ({
  item_id: 'i1', selection: { start: 7.54, end: 9.02 }, old_text: 'Start a live Bajicam session.', new_text: 'Start a live Bhaji Cam session.',
  speaker: 'A', mix: 'replace', reason: '', kind: 'planned', enabled: true, status: 'ready', fit: null, candidate: take(),
  edit_id: null, question: null, error: null, note: null, progress: null, ...over,
})
const handlers = () => ({
  onSeek: vi.fn(), onHear: vi.fn(), onAdd: vi.fn(), onDiscard: vi.fn(), onUndo: vi.fn(),
  onRemove: vi.fn(), onHearTake: vi.fn(),
})
const doc = (props: Partial<Parameters<typeof LineDoc>[0]> = {}) => {
  const h = handlers()
  render(<LineDoc statements={STATEMENTS} currentTime={0} speakers={SPEAKERS} voices={VOICES} {...h} {...props} />)
  return h
}
const KEY = keyOf({ start: 7.54, end: 9.02 })

describe('LineDoc: the line is the unit', () => {
  it('lists lines with their times and who says each (Volt)', () => {
    doc({ currentTime: 8 })
    expect(screen.getByText('0:07')).toBeInTheDocument()
    expect(screen.getByText('Start a live Bajicam session.').closest('[data-current]')).toHaveAttribute('data-current', 'true')
    expect(screen.getAllByText('the Customer').length).toBeGreaterThan(0)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('offers the same verbs on a line as shot: Hear it, Edit it, Discard (20e)', async () => {
    const h = doc()
    const actions = screen.getByRole('group', { name: 'Actions for 0:07' })
    expect(within(actions).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent?.replace(/[␣K]$/, ''))).toEqual(
      ['Hear it', 'Edit it', 'Discard', 'Add a line after'])
    await userEvent.click(within(actions).getByRole('button', { name: 'Discard' }))
    expect(h.onRemove).toHaveBeenCalledWith(STATEMENTS[1])   // a removal is proposed, not done
    await userEvent.click(within(actions).getByRole('button', { name: 'Hear it' }))
    expect(h.onSeek).toHaveBeenCalledWith(STATEMENTS[1])
  })

  it('offers Hear it, Add it, Edit it, Discard on a proposal, and Add all when there are several (20e)', async () => {
    const second = item({ item_id: 'i2', selection: { start: 9.38, end: 9.88 }, old_text: 'Sure, sir.', new_text: 'Sure, boss.',
      candidate: take({ candidate_id: 'c2', plan: { ...take().plan, selection: { start: 9.38, end: 9.88 }, new_text: 'Sure, boss.' } }) })
    const onAddAll = vi.fn()
    const h = doc({ items: [item(), second], onAddAll })
    const verbs = screen.getByRole('group', { name: 'Proposal at 0:07' })
    expect(within(verbs).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent?.replace(/[␣K]$/, ''))).toEqual(['Hear it', 'Add it', 'Edit it', 'Discard'])
    expect(screen.getAllByText('Proposed')).toHaveLength(2)
    expect(screen.getByText(/one transcript|2 lines are proposed/i)).toHaveTextContent('2 lines are proposed')
    await userEvent.click(within(verbs).getByRole('button', { name: 'Hear it' }))
    expect(h.onHearTake).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }), expect.objectContaining({ candidate_id: 'c1' }))
    await userEvent.click(within(verbs).getByRole('button', { name: 'Add it' }))
    expect(h.onAdd).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
    await userEvent.click(within(verbs).getByRole('button', { name: 'Discard' }))
    expect(h.onDiscard).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
    await userEvent.click(within(verbs).getByRole('button', { name: 'Edit it' }))
    expect(screen.getByTestId('depth')).toBeInTheDocument()   // Volt: the proposal opens in place
    await userEvent.click(screen.getByRole('button', { name: 'Change the words' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Start a live Bhaji Cam session.')
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'Add all 2' }))
    expect(onAddAll).toHaveBeenCalledWith([expect.objectContaining({ item_id: 'i1' }), expect.objectContaining({ item_id: 'i2' })])
  })

  it('says why a flagged take is flagged, and still offers Add it (20e)', () => {
    const flagged = take({ continuity: { voice_match: null, prosody: 0.5, audio_integration: 0.99, lip_sync: null, passed: false,
      warnings: ['Sounds less natural than it should (naturalness 2.2, wants 3.0).'], measured: ['prosody'] } })
    doc({ items: [item({ candidate: flagged })] })
    expect(screen.getByTestId('take')).toHaveTextContent("Brian's voice · Sounds less natural than it should (naturalness 2.2, wants 3.0). Trimmed 120 ms of pauses. Add it anyway if it sounds right to you.")
    expect(within(screen.getByRole('group', { name: 'Proposal at 0:07' })).getByRole('button', { name: 'Add it' })).toBeEnabled()
  })

  it('shows a proposed removal struck through, with Remove it and Discard (20e)', async () => {
    const removal = item({ item_id: 'r', mix: 'remove', new_text: '', candidate: take({ plan: { ...take().plan, new_text: '', mix: 'remove' } }) })
    const h = doc({ items: [removal] })
    expect(screen.getByText('Start a live Bajicam session.').tagName).toBe('DEL')
    expect(screen.getByText(/Proposed: these words go/)).toBeInTheDocument()
    const verbs = screen.getByRole('group', { name: 'Proposal at 0:07' })
    expect(within(verbs).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent?.replace(/[␣K]$/, ''))).toEqual(['Hear it', 'Remove it', 'Discard'])
    await userEvent.click(within(verbs).getByRole('button', { name: 'Remove it' }))
    expect(h.onAdd).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'r' }))
  })

  it('mixes a line under the words or back to the front, without voicing it again (20g)', async () => {
    const onLevel = vi.fn()
    doc({
      onLevel,
      revisions: [
        { edit_id: 'e1', start: 0.4, end: 6.9, text: 'Golden sands.', mix: 'layer' },
        { edit_id: 'e2', start: 0.4, end: 1.8, text: 'Woohoo!', mix: 'layer', level_db: -12 },
      ],
      items: [item({ item_id: 'i3', selection: { start: 0.4, end: 1.8 }, mix: 'layer', old_text: '', new_text: 'Yeahhh!',
        candidate: take({ candidate_id: 'c3', plan: { ...take().plan, selection: { start: 0.4, end: 1.8 }, new_text: 'Yeahhh!', mix: 'layer' } }) })],
    })
    const rows = screen.getAllByRole('listitem', { name: /added line at 0:00|proposed line at 0:00/i })
    expect(rows[1]).toHaveTextContent('background (-12 dB)')
    await userEvent.click(within(rows[1]).getByRole('button', { name: 'Make it foreground' }))
    expect(onLevel).toHaveBeenLastCalledWith({ editId: 'e2' }, 0)
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Make it background' }))
    expect(onLevel).toHaveBeenLastCalledWith({ editId: 'e1' }, -12)
    await userEvent.click(within(rows[2]).getByRole('button', { name: 'Make it background' }))
    expect(onLevel).toHaveBeenLastCalledWith({ candidate: expect.objectContaining({ candidate_id: 'c3' }), item: expect.objectContaining({ item_id: 'i3' }) }, -12)
    // Only added lines carry a level: two controls for the two foreground layers, none on the spoken lines.
    expect(screen.getAllByRole('button', { name: /make it background/i })).toHaveLength(2)
  })

  it('numbers an unnamed speaker in order of appearance (20e)', () => {
    doc({ speakers: [{ label: 'A', name: '', voice_id: null }, { label: 'B', name: '', voice_id: null }] })
    expect(screen.getByRole('listitem', { name: 'Line at 0:05, Speaker 1' })).toBeInTheDocument()
    expect(screen.getByRole('listitem', { name: 'Line at 0:09, Speaker 2' })).toBeInTheDocument()
  })

  it('edits a line in place: wording shown as a change, delivery, voice, cost, Voice it', async () => {
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
    await userEvent.click(screen.getByRole('button', { name: 'Voice it' }))
    expect(h.onHear).toHaveBeenCalledWith(KEY, {
      selection: { start: 7.54, end: 9.02 }, text: 'Start a live Bhaji Cam session.', voiceId: 'nPczCjzI2devNBz1zQrb',
      delivery: 'warmer', mix: 'replace',
    })
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
  })

  it('does not hear an unchanged line, and cancels with Escape', async () => {
    const h = doc()
    await userEvent.click(screen.getByText('Sure, sir.'))
    expect(screen.getByRole('button', { name: 'Voice it' })).toBeDisabled()
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
    await userEvent.click(screen.getByRole('button', { name: /^\+ add a line$/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Hold the picture' }))
    await userEvent.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Bye!{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(addKeyOf(STATEMENTS[2]), expect.objectContaining({ mix: 'concatenate' }))
  })

  it("shows a proposal's facts on its own line: whose voice and the verdict in words (20e)", () => {
    doc({ items: [item()] })
    const facts = screen.getByTestId('take')
    expect(facts).toHaveTextContent("Brian's voice · Sounds like the Customer, and sits in the room. Trimmed 120 ms of pauses.")
    expect(screen.getByText('Proposed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /another take|^keep$/i })).toBeNull()
  })

  it('shows what is happening to a line, and the state of one that needs you or failed — nothing to answer here', () => {
    doc({
      items: [
        item({ item_id: 'w', selection: { start: 5.2, end: 6.94 }, status: 'working', candidate: null, progress: 'Take 1: pitch is 6 semitones off. Trying again (take 2 of 3)' }),
        item({ item_id: 'n', status: 'needs-you', candidate: null }),
        item({ item_id: 'f', selection: { start: 9.38, end: 9.88 }, status: 'failed', candidate: null, error: 'The voice service was busy. Nothing was charged.' }),
      ],
      pendingLines: [
        { selection: { start: 5.2, end: 6.94 }, status: 'working' },
        { selection: { start: 7.54, end: 9.02 }, status: 'needs-you' },
        { selection: { start: 9.38, end: 9.88 }, status: 'failed' },
      ],
    })
    expect(screen.getByTestId('line-working')).toHaveTextContent('Trying again')
    expect(screen.getByText('Voicing…')).toBeInTheDocument()
    expect(screen.getByText('Waiting on you')).toBeInTheDocument()
    expect(screen.getByText("Couldn't voice it")).toBeInTheDocument()
    // What a line needs is said to Voltage in the box; the row has no answers or retries of its own.
    expect(screen.queryByTestId('line-needs-you')).toBeNull()
    expect(screen.queryByRole('button', { name: /try again|dismiss|shorter line/i })).toBeNull()
  })

  it('shows an added change inline with Take it out, and a removed line struck through with Put it back', async () => {
    const h = doc({ revisions: [
      { edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' },
      { edit_id: 'e2', start: 9.38, end: 9.88, text: '', mix: 'remove' },
    ] })
    const kept = screen.getByTestId('revision')
    expect(within(kept).getByText('Bhaji Cam').tagName).toBe('INS')
    expect(screen.getByText('✓ In the video')).toBeInTheDocument()
    expect(screen.getByText('Removed')).toBeInTheDocument()
    expect(screen.getByText('Sure, sir.').tagName).toBe('DEL')
    const added = screen.getByRole('group', { name: 'Added line at 0:07' })
    expect(within(added).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent?.replace(/[␣K]$/, ''))).toEqual(['Hear it', 'Take it out', 'Edit it'])
    await userEvent.click(within(added).getByRole('button', { name: 'Take it out' }))
    expect(h.onUndo).toHaveBeenCalledWith('e1')
    await userEvent.click(screen.getByRole('button', { name: 'Put it back' }))
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

  it('tells the panel what is open, and has no wording or long-line controls of its own', async () => {
    const onEditingChange = vi.fn()
    doc({ onEditingChange })
    await userEvent.click(screen.getByText('Sure, sir.'))
    expect(onEditingChange).toHaveBeenLastCalledWith(STATEMENTS[2])
    expect(screen.queryByRole('combobox', { name: /runs long/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /ask voltage/i })).toBeNull()
    await userEvent.keyboard('{Escape}')
    expect(onEditingChange).toHaveBeenLastCalledWith(null)
  })
})

describe('LineDoc: editing starts from where the line stands', () => {
  it('reopens with the last wording Voltage tried, and the choices you made', async () => {
    const tried = item({ new_text: 'Start a Bhaji Cam session now.', delivery: 'warmer', candidate: take({ plan: { ...take().plan, voice_profile_id: 'EXAVITQu4vr4xnSDxMaL' } }) })
    doc({ items: [tried] })
    await userEvent.click(within(screen.getByRole('group', { name: 'Proposal at 0:07' })).getByRole('button', { name: 'Edit it' }))
    await userEvent.click(screen.getByRole('button', { name: 'Change the words' }))
    expect(screen.getByRole('textbox', { name: /new wording/i })).toHaveValue('Start a Bhaji Cam session now.')
    expect(screen.getByRole('combobox', { name: 'Voice' })).toHaveValue('EXAVITQu4vr4xnSDxMaL')
    expect(screen.getByRole('button', { name: 'Warmer' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Voice it' })).toBeEnabled()   // it differs from the line as it stands
  })

  it('reopens a kept line with its kept wording, and measures the change from there', async () => {
    doc({ revisions: [{ edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' }] })
    await userEvent.click(within(screen.getByRole('group', { name: 'Added line at 0:07' })).getByRole('button', { name: 'Edit it' }))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    expect(box).toHaveValue('Start a live Bhaji Cam session.')
    expect(screen.getByRole('button', { name: 'Voice it' })).toBeDisabled()
    await userEvent.type(box, ' Now.')
    expect(screen.getByText(/you'd be changing/i)).not.toHaveTextContent('Bajicam')
    expect(within(screen.getByText(/you'd be changing/i)).getByText('Now.').tagName).toBe('INS')
  })

  it('shows a failed added line as its own row, with its reason and Discard (20f)', () => {
    const added = item({ item_id: 'i2', selection: { start: 9.38, end: 9.88 }, mix: 'over', status: 'failed', candidate: null, new_text: 'Everything is 30% off.', error: 'The voice service was busy.' })
    const h = doc({ items: [added] })
    const row = screen.getByRole('listitem', { name: 'Proposed line at 0:09' })
    expect(row).toHaveTextContent('Everything is 30% off.')
    expect(row).toHaveTextContent('The voice service was busy.')
    expect(within(row).getByText("Couldn't voice it")).toBeInTheDocument()
    within(row).getByRole('button', { name: 'Discard' }).click()
    expect(h.onDiscard).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i2' }))
  })

  it('gives every audio line its own row, however many play at once (20f)', async () => {
    // Two added lines in the video at the same moment, and a proposal over them: three rows, each with its own words.
    const h = doc({
      revisions: [
        { edit_id: 'e1', start: 0.4, end: 6.9, text: 'Golden sands, endless sunsets.', mix: 'layer' },
        { edit_id: 'e2', start: 0.4, end: 1.8, text: 'Woohoo!', mix: 'layer' },
      ],
      items: [item({ item_id: 'i3', selection: { start: 0.4, end: 1.8 }, mix: 'layer', old_text: '', new_text: 'Yeahhh!',
        candidate: take({ candidate_id: 'c3', plan: { ...take().plan, selection: { start: 0.4, end: 1.8 }, new_text: 'Yeahhh!', mix: 'layer' } }) })],
    })
    const rows = screen.getAllByRole('listitem', { name: /added line at 0:00|proposed line at 0:00/i })
    expect(rows.map((r) => r.getAttribute('aria-label'))).toEqual(['Added line at 0:00', 'Added line at 0:00', 'Proposed line at 0:00'])
    expect(rows[0]).toHaveTextContent('Golden sands, endless sunsets.')
    expect(rows[0]).toHaveTextContent('with 3 other lines at this moment')   // the other layer, the proposal, and the spoken line it runs under
    expect(rows[1]).toHaveTextContent('Woohoo!')
    expect(rows[2]).toHaveTextContent('Yeahhh!')
    expect(screen.getAllByText('✓ In the video')).toHaveLength(2)
    expect(screen.getByText('Proposed')).toBeInTheDocument()
    // The spoken lines keep their own words: a layer over them is not a change to them.
    expect(screen.getByText('Hi, I want to buy groceries.')).toBeInTheDocument()
    // Take it out on the second layer; Edit it on the first asks for a redo that swaps the edit.
    const second = within(rows[1]).getByRole('group', { name: 'Added line at 0:00' })
    await userEvent.click(within(second).getByRole('button', { name: 'Take it out' }))
    expect(h.onUndo).toHaveBeenCalledWith('e2')
    await userEvent.click(within(within(rows[0]).getByRole('group', { name: 'Added line at 0:00' })).getByRole('button', { name: 'Edit it' }))
    const box = screen.getByRole('textbox', { name: /new wording/i })
    expect(box).toHaveValue('Golden sands, endless sunsets.')
    await userEvent.clear(box)
    await userEvent.type(box, 'Golden sands.{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(keyOf({ start: 0.4, end: 6.9 }), expect.objectContaining({ text: 'Golden sands.', mix: 'layer', editId: 'e1', before: 'Golden sands, endless sunsets.' }))
    // Edit it on the proposal voices that item again.
    await userEvent.click(within(screen.getByRole('group', { name: 'Proposal at 0:00' })).getByRole('button', { name: 'Edit it' }))
    await userEvent.click(screen.getByRole('button', { name: 'Change the words' }))
    await userEvent.type(screen.getByRole('textbox', { name: /new wording/i }), ' Woo!{Enter}')
    expect(h.onHear).toHaveBeenLastCalledWith(keyOf({ start: 0.4, end: 1.9 }), expect.objectContaining({ text: 'Yeahhh! Woo!', mix: 'layer', itemId: 'i3' }))   // the row spans the take's own length
  })
})

describe('LineDoc: a take can go anywhere on the timeline', () => {
  it('shows where a take starts and lets you move it: drag on the bar, or type a time', async () => {
    const onPlacing = vi.fn()
    const onMove = vi.fn()
    const first = doc({ items: [item()], onPlacing, onMove })
    const place = screen.getByTestId('place')
    expect(place).toHaveTextContent('Starts at 0:07.54')
    await userEvent.click(within(place).getByRole('button', { name: 'Move' }))
    expect(onPlacing).toHaveBeenCalledWith({ id: 'c1', start: 7.54, duration: 1.5 })
    void first
  })

  it('applies the placed start to the take', async () => {
    const onMove = vi.fn()
    const onPlacing = vi.fn()
    doc({ items: [item()], onMove, onPlacing, placing: { id: 'c1', start: 9.2, duration: 1.5 } })
    const place = screen.getByTestId('place')
    await userEvent.click(within(place).getByRole('button', { name: 'Nudge later' }))
    expect(onPlacing).toHaveBeenCalledWith({ id: 'c1', start: 9.3, duration: 1.5 })
    const field = within(place).getByRole('textbox', { name: 'Starts at' })
    await userEvent.clear(field)
    await userEvent.type(field, '0:10.00')
    expect(onPlacing).toHaveBeenLastCalledWith({ id: 'c1', start: 10, duration: 1.5 })
    await userEvent.click(within(place).getByRole('button', { name: 'Put it here' }))
    expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }), expect.objectContaining({ candidate_id: 'c1' }), 9.2)   // the prop's start wins until re-rendered
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
    await userEvent.click(screen.getByRole('button', { name: /^\+ add a line$/i }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Starts at' }), '0:03.50')
    await userEvent.type(screen.getByRole('textbox', { name: /words for the new line/i }), 'Welcome to Goa.{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(addKeyOf(STATEMENTS[2]), expect.objectContaining({ text: 'Welcome to Goa.', mix: 'over', at: 3.5 }))
  })
})


describe('LineDoc: keyboard (UX-4)', () => {
  it('moves between lines, opens and closes the editor, hears, adds, takes out and discards from the keys', async () => {
    const user = userEvent.setup()
    const h = doc({
      items: [item()],
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
    expect(h.onAdd).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
    await user.keyboard('{Enter}')
    expect(screen.getByRole('textbox', { name: 'New wording' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
    await waitFor(() => expect(row(1)).toHaveFocus())
    await user.keyboard('{ArrowDown}')
    await user.keyboard('u')
    expect(h.onUndo).toHaveBeenCalledWith('e1')
    await user.keyboard('{ArrowUp}')
    expect(row(1)).toHaveFocus()
    await user.keyboard('{Delete}')   // on a proposal, Delete discards it
    expect(h.onDiscard).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
    await user.keyboard('{ArrowUp}')
    expect(row(0)).toHaveFocus()
    await user.keyboard('{Delete}')   // on a line as shot, Delete proposes removing it
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
    expect(h.onAdd).not.toHaveBeenCalled()
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
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: /move the line at 0:12/i })).toBeInTheDocument()
    // The line it landed on is left alone.
    expect(screen.queryByText('✓ In the video')).not.toBeInTheDocument()
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

describe('LineDoc: the transcript agrees with the record (p60)', () => {
  const ERR = 'Too long for its gap: needs 3.8 s, has 2.3 s. Ask Voltage to shorten it, or let the picture ease.'

  it('counts in the heading exactly the items that are ready', () => {
    doc({ items: [
      item(),
      item({ item_id: 'i2', selection: { start: 9.38, end: 9.88 }, old_text: 'Sure, sir.', new_text: 'Of course, sir.', status: 'failed', candidate: null, error: ERR }),
    ] })
    expect(screen.getByTestId('counts')).toHaveTextContent(/^1 proposed/)
  })

  it('shows Couldn’t voice it only when the latest attempt failed, with Ask Voltage to try again', async () => {
    const onRetry = vi.fn()
    const failed = item({ status: 'failed', candidate: null, error: ERR })
    doc({ items: [failed], onRetry })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    expect(row).toHaveTextContent("Couldn't voice it")
    expect(row).toHaveTextContent(ERR)
    expect(row.textContent).not.toMatch(/—|widen the selection/)
    await userEvent.click(within(row).getByRole('button', { name: 'Ask Voltage to try again' }))
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
  })

  it('keeps a line with a good take proposed when a later try failed, and says so', () => {
    doc({ items: [item({ note: 'The last try could not be made; the take before it stands.' })] })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    expect(row).toHaveTextContent('Proposed')
    expect(row).not.toHaveTextContent("Couldn't voice it")
    expect(screen.getByTestId('item-note')).toHaveTextContent('the take before it stands')
  })

  it('says the picture’s flex once', () => {
    doc({ items: [item({ candidate: take({ plan: { ...take().plan, flex: 0.94 }, fit_notes: ['nearest of 3 takes', 'opened the pauses by 36 ms', 'the picture at 0.94×'] }) })] })
    const meta = screen.getByTestId('take')
    expect(meta).toHaveTextContent('Picture eased to 0.94× for this line.')
    expect(meta.textContent!.match(/0\.94/g)).toHaveLength(1)
    expect(meta).not.toHaveTextContent(/flexed/)
  })
})
