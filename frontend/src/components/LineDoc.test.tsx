import { describe, it, expect, vi } from 'vitest'
import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LineDoc } from './LineDoc'
import { keyOf, addKeyOf } from '../transcript/keys'
import type { ActivityJob, Candidate, PlanItem } from '../types'
import type { ArrangementView } from '../api'
import { EMPTY, overrun, place, specs } from '../transcript/arrange'
import type { Arrangement } from '../transcript/arrange'

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
    expect(screen.getAllByText('Ready to hear')).toHaveLength(2)
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

  it('gives every added line a role, Voice, Bed or Effect, with one line of facts, and none to a spoken line (2026-10-20)', async () => {
    const onRole = vi.fn(async () => null)
    doc({
      onRole,
      mixLines: [{ edit_id: 'e2', candidate_id: 'x', role: 'bed', start: 0.4, end: 1.8, gain_db: -9, level_lufs: -33, under_db: 15.2, alone: false, ducks: true, ratio_db: null, covered_by: null, flag: null },
        { edit_id: 'e1', candidate_id: 'y', role: 'voice', start: 0.4, end: 6.9, gain_db: 0, level_lufs: -18, under_db: null, alone: false, ducks: false, ratio_db: 6, covered_by: 'e3', flag: '“cheers” covers this line at 0:00; lower it or make it a Bed.' }],
      revisions: [
        { edit_id: 'e1', start: 0.4, end: 6.9, text: 'Golden sands.', mix: 'layer' },
        { edit_id: 'e2', start: 0.4, end: 1.8, text: 'Woohoo!', mix: 'layer', role: 'bed' },
      ],
      items: [item({ item_id: 'i3', selection: { start: 0.4, end: 1.8 }, mix: 'layer', old_text: '', new_text: 'Yeahhh!',
        candidate: take({ candidate_id: 'c3', plan: { ...take().plan, selection: { start: 0.4, end: 1.8 }, new_text: 'Yeahhh!', mix: 'layer' } }) })],
    })
    const rows = screen.getAllByRole('listitem', { name: /added line at 0:00|proposed line at 0:00/i })
    const bed = rows.find((r) => r.textContent?.includes('Woohoo!'))!
    expect(within(bed).getByTestId('role-facts')).toHaveTextContent('Bed · sits 15 dB under the voices · ducks while they speak')
    expect(within(within(bed).getByRole('group', { name: 'What this line is in the mix' })).getByRole('button', { name: 'Bed' })).toHaveAttribute('aria-pressed', 'true')
    const voice = rows.find((r) => r.textContent?.includes('Golden sands.'))!
    expect(within(voice).getByTestId('mix-flag')).toHaveTextContent('“cheers” covers this line at 0:00; lower it or make it a Bed.')
    await userEvent.click(within(voice).getByRole('button', { name: 'Effect' }))
    expect(onRole).toHaveBeenLastCalledWith({ editId: 'e1' }, { role: 'effect', offset_db: 0 })
    const proposal = rows.find((r) => r.textContent?.includes('Yeahhh!'))!
    await userEvent.click(within(proposal).getByRole('button', { name: 'Bed' }))
    expect(onRole).toHaveBeenLastCalledWith({ candidate: expect.objectContaining({ candidate_id: 'c3' }), item: expect.objectContaining({ item_id: 'i3' }) }, { role: 'bed', offset_db: 0 })
    // Only added lines have a role: three controls for the three added lines, none on the spoken lines.
    expect(screen.getAllByRole('group', { name: 'What this line is in the mix' })).toHaveLength(3)
  })

  it('asks before the only speech in its span becomes a Bed, and fine-tunes with Hear it in place', async () => {
    const question = { question: 'This is the only speech here. As a Bed it would just be quieter. Keep it as Voice, or play it quietly under (Voice at -8 dB)?',
      options: [{ label: 'Keep it as Voice', role: 'voice' as const, offset_db: 0 }, { label: 'Play it quietly under', detail: 'Voice at -8 dB', role: 'voice' as const, offset_db: -8 },
        { label: 'Make it a Bed anyway', role: 'bed' as const, offset_db: 0, confirm: true }] }
    const onRole = vi.fn().mockResolvedValueOnce(question).mockResolvedValue(null)
    const h = doc({ onRole, revisions: [{ edit_id: 'e1', start: 0.4, end: 6.9, text: 'Golden sands.', mix: 'layer' }] })
    const row = screen.getByRole('listitem', { name: /added line at 0:00/i })
    await userEvent.click(within(row).getByRole('button', { name: 'Bed' }))
    const card = await within(row).findByTestId('role-question')
    expect(card).toHaveTextContent('This is the only speech here.')
    await userEvent.click(within(card).getByRole('button', { name: /Play it quietly under/ }))
    expect(onRole).toHaveBeenLastCalledWith({ editId: 'e1' }, { role: 'voice', offset_db: -8, confirm: undefined })
    await waitFor(() => expect(within(row).queryByTestId('role-question')).not.toBeInTheDocument())
    await userEvent.click(within(row).getByRole('button', { name: 'Fine-tune' }))
    const slider = within(row).getByRole('slider')
    expect(slider).toHaveAttribute('min', '-24')
    expect(slider).toHaveAttribute('max', '6')
    fireEvent.change(slider, { target: { value: '-5' } })
    fireEvent.pointerUp(slider)
    expect(onRole).toHaveBeenLastCalledWith({ editId: 'e1' }, { role: 'voice', offset_db: -5 })
    await userEvent.click(within(row).getByRole('button', { name: 'Hear it in place' }))
    expect(h.onSeek).toHaveBeenCalled()
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
    expect(screen.getByText('Ready to hear')).toBeInTheDocument()
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
    expect(screen.getByText('Voicing')).toBeInTheDocument()
    expect(screen.getByText('Waiting on you')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
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

  it('voices a line whose words stay the same when its delivery or voice changes', async () => {
    const h = doc()
    await userEvent.click(screen.getByText('Sure, sir.'))
    const voiceIt = screen.getByRole('button', { name: 'Voice it' })
    expect(voiceIt).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'More excited' }))
    expect(voiceIt).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'As spoken' }))
    expect(voiceIt).toBeDisabled()
    const voice = screen.getByRole('combobox', { name: 'Voice' })
    await userEvent.selectOptions(voice, within(voice).getAllByRole('option').find((o) => (o as HTMLOptionElement).value !== (voice as HTMLSelectElement).value)!)
    expect(voiceIt).toBeEnabled()
    await userEvent.click(voiceIt)
    expect(h.onHear).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ text: 'Sure, sir.', mix: 'replace' }))
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
    expect(within(row).getByText('Failed')).toBeInTheDocument()
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
    expect(screen.getByText('Ready to hear')).toBeInTheDocument()
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

  it('moves a kept line with its replacement, in the arrangement', () => {
    const onArrange = vi.fn()
    doc({ revisions: [{ edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' }],
      arranged: view(), onArrange })
    expect(screen.getByRole('button', { name: /move the line at 0:07/i })).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('listitem', { name: 'Line at 0:07, the Customer' }), { key: 'ArrowDown', altKey: true })
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ order: ['L0', 'L2', 'L1'] }))
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


/** The arrangement as the server would send it for STATEMENTS. */
const view = (arrangement: Partial<Arrangement> = {}, extra: Partial<ArrangementView> = {}): ArrangementView => {
  const lines = specs(STATEMENTS)
  const full = { ...EMPTY, ...arrangement }
  const placed = place(lines, full)
  return {
    arrangement: full, duration: 10, overrun: overrun(placed, 10), ease_ok: false, min_gap_default: 0.15, can_undo: false,
    lines: placed.map((p) => {
      const i = Number(p.key.slice(1))
      const ln = lines[i]
      return { ...p, index: i + 1, text: STATEMENTS[i].text, speaker: STATEMENTS[i].speaker, orig_start: ln.orig_start, orig_end: ln.orig_end, length: ln.length, gap: ln.gap, replaced_by: null }
    }),
    ...extra,
  }
}
const rowLabels = () => screen.getAllByRole('listitem', { name: /^line at/i }).map((r) => r.getAttribute('aria-label'))

describe('LineDoc: the arrangement, the transcript in playback order (2026-10-19)', () => {
  it('lists every line once, in the order it plays, with where it was shot and the lips warning', () => {
    doc({ arranged: view({ order: ['L1', 'L0', 'L2'] }), onArrange: vi.fn() })
    // The second line plays first, at the clip's lead-in; the first follows after the pause that followed it.
    expect(rowLabels()).toEqual(['Line at 0:05, the Customer', 'Line at 0:07, the Customer', 'Line at 0:09, the Shopkeeper'])
    const rows = screen.getAllByRole('listitem', { name: /^line at/i })
    expect(rows[0]).toHaveTextContent('Start a live Bajicam session.')
    expect(rows[1]).toHaveTextContent('Hi, I want to buy groceries.')
    expect(screen.getAllByText('Start a live Bajicam session.')).toHaveLength(1)
    expect(screen.getAllByTestId('lips')[0]).toHaveTextContent("Lines move, the picture doesn't. If the Customer is on screen here, the lips won't match.")
    expect(screen.queryByText(/Moved away/)).not.toBeInTheDocument()
  })

  it('shows the original timing on request', async () => {
    const user = userEvent.setup()
    doc({ arranged: view({ order: ['L1', 'L0', 'L2'] }), onArrange: vi.fn() })
    await user.click(screen.getByRole('button', { name: 'Show original timing' }))
    expect(screen.getAllByRole('listitem', { name: /^line at/i })[0]).toHaveTextContent('Hi, I want to buy groceries.')
    expect(screen.queryByTestId('lips')).not.toBeInTheDocument()
  })

  it('drags a line: the rows take their new places live, Escape lets go, and the drop is one action', () => {
    const onArrange = vi.fn()
    const onPreview = vi.fn()
    doc({ arranged: view(), onArrange, onPreview })
    const box = () => screen.getAllByRole('listitem', { name: /^line at/i }).forEach((el, k) => {
      el.getBoundingClientRect = () => ({ top: k * 100, height: 100, bottom: k * 100 + 100, left: 0, right: 500, width: 500, x: 0, y: k * 100, toJSON: () => ({}) })
    })
    box()
    fireEvent.pointerDown(screen.getByRole('button', { name: /move the line at 0:05/i }), { clientY: 50 })
    fireEvent.pointerMove(window, { clientY: 280 })
    // The first line now sits last: the bar above it says where it starts, the others moved up.
    expect(screen.getByTestId('insertion-bar')).toHaveTextContent('Starts at 0:08.14')
    expect(onPreview).toHaveBeenLastCalledWith(expect.arrayContaining([expect.objectContaining({ key: 'L0', start: 8.14 })]))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onArrange).not.toHaveBeenCalled()
    expect(screen.queryByTestId('insertion-bar')).not.toBeInTheDocument()

    box()
    fireEvent.pointerDown(screen.getByRole('button', { name: /move the line at 0:05/i }), { clientY: 50 })
    fireEvent.pointerMove(window, { clientY: 280 })
    fireEvent.pointerUp(window)
    expect(onArrange).toHaveBeenCalledTimes(1)
    expect(onArrange).toHaveBeenCalledWith({ order: ['L1', 'L2', 'L0'], pins: {}, min_gap: null, end: null })
  })

  it('moves a line with Alt and the arrow keys, and from its menu', async () => {
    const user = userEvent.setup()
    const onArrange = vi.fn()
    doc({ arranged: view(), onArrange })
    fireEvent.keyDown(screen.getByRole('listitem', { name: 'Line at 0:07, the Customer' }), { key: 'ArrowUp', altKey: true })
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ order: ['L1', 'L0', 'L2'] }))
    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:05' })).getByRole('button', { name: 'Move down' }))
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ order: ['L1', 'L0', 'L2'] }))
    expect(within(screen.getByRole('group', { name: 'Actions for 0:05' })).queryByRole('button', { name: 'Move up' })).not.toBeInTheDocument()
  })

  it('pins a line at a typed start with Enter, and the pin unpins it', async () => {
    const user = userEvent.setup()
    const onArrange = vi.fn()
    doc({ arranged: view(), onArrange })
    await user.click(within(screen.getByRole('group', { name: 'Actions for 0:09' })).getByRole('button', { name: 'Starts at…' }))
    const field = screen.getByRole('textbox', { name: 'Starts at' })
    await user.clear(field)
    await user.type(field, '0:02.5{Enter}')
    expect(onArrange).toHaveBeenLastCalledWith({ order: [], pins: { L2: 2.5 }, min_gap: null, end: null })
  })

  it('says a line was pushed after a pinned one, and unpins from the pin', async () => {
    const user = userEvent.setup()
    const onArrange = vi.fn()
    doc({ arranged: view({ pins: { L2: 5.0 } }), onArrange })
    expect(screen.getByTestId('pushed')).toHaveTextContent('pushed after 0:05.00 (pinned)')
    await user.click(screen.getByRole('button', { name: /^Pinned\. Unpin it/ }))
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ pins: {} }))
  })

  it('never cuts silently past the end: tighten, ease or trim', async () => {
    const user = userEvent.setup()
    const onArrange = vi.fn()
    doc({ arranged: view({ pins: { L2: 9.8 } }, { ease_ok: true }), onArrange })
    expect(screen.getByTestId('overrun')).toHaveTextContent('Runs 0.3 s past the end')
    await user.click(within(screen.getByTestId('overrun')).getByRole('button', { name: 'Trim the last line' }))
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ end: 'trim' }))
    await user.click(within(screen.getByTestId('overrun')).getByRole('button', { name: 'Tighten gaps' }))
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ min_gap: 0.15 }))
  })

  it('tightens the gaps to a chosen pause, and undoes the last move', async () => {
    const user = userEvent.setup()
    const onArrange = vi.fn()
    const onArrangeUndo = vi.fn()
    doc({ arranged: view({}, { can_undo: true }), onArrange, onArrangeUndo })
    const gap = screen.getByRole('textbox', { name: 'Longest pause, in seconds' })
    await user.clear(gap)
    await user.type(gap, '0.2')
    await user.click(within(screen.getByTestId('arrange-bar')).getByRole('button', { name: 'Tighten gaps' }))
    expect(onArrange).toHaveBeenLastCalledWith(expect.objectContaining({ min_gap: 0.2 }))
    await user.click(screen.getByRole('button', { name: 'Undo the last move' }))
    expect(onArrangeUndo).toHaveBeenCalledTimes(1)
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

  it('shows Failed only when the latest attempt failed, with its reason and Retry', async () => {
    const onRetry = vi.fn()
    const failed = item({ status: 'failed', candidate: null, error: ERR })
    doc({ items: [failed], onRetry })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    expect(row).toHaveTextContent('Failed')
    expect(row).toHaveTextContent(ERR)
    expect(row.textContent).not.toMatch(/—|widen the selection/)
    await userEvent.click(within(row).getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
  })

  it('keeps a line with a good take proposed when a later try failed, and says so', () => {
    doc({ items: [item({ note: 'The last try could not be made; the take before it stands.' })] })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    expect(row).toHaveTextContent('Ready to hear')
    expect(row).not.toHaveTextContent('Failed')
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

describe('LineDoc: one chip per line, read from the jobs (2026-10-20)', () => {
  const job = (over: Partial<ActivityJob> = {}): ActivityJob => ({
    job_id: 'J1', video_id: 'p1', turn_id: 't1', kind: 'voice_line', status: 'queued', step_label: 'Queued', progress: 0,
    line_ids: ['i1'], created_at: '2026-10-20T10:00:00Z', started_at: null, finished_at: null, eta_s: 9,
    error_code: null, error_text: null, cost_usd: null, ...over,
  })
  const none = { candidate_ids: [], edit_ids: [], item_ids: [] }
  const chips = () => screen.getAllByTestId('row-chip').map((c) => c.textContent)

  it('every line carries exactly one chip: Original for a line nobody touched', () => {
    doc({ activity: { jobs: [], video: null, rendering: null } })
    expect(chips()).toEqual(['Original', 'Original', 'Original'])
  })

  it('goes Queued, Voicing with a slim bar, Ready to hear, Rendering, In the preview', () => {
    const planned = item({ status: 'planned', candidate: null })
    const { rerender } = render(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} items={[planned]} activity={{ jobs: [job()], video: null, rendering: null }} />)
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('Queued')
    rerender(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} items={[{ ...planned, status: 'working' }]}
      activity={{ jobs: [job({ status: 'running', progress: 0.5, step_label: 'Checking fit' })], video: null, rendering: null }} />)
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('Voicing')
    expect(screen.getByTestId('line-working')).toHaveTextContent('Checking fit · about 9 s')
    expect(screen.getByTestId('line-progress')).toHaveAttribute('aria-valuenow', '50')
    const done = [job({ status: 'done' })]
    rerender(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} items={[item()]} activity={{ jobs: done, video: none, rendering: null }} />)
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('Ready to hear')
    rerender(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} items={[item()]} activity={{ jobs: done, video: none, rendering: { ...none, candidate_ids: ['c1'] } }} />)
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('Rendering')
    rerender(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} items={[item()]} activity={{ jobs: done, video: { ...none, item_ids: ['i1'] }, rendering: null }} />)
    // Rehearsal item 7: a proposal not yet added is in the with-proposals preview, not in the video.
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('In the preview')
  })

  it('a failed line says why and retries the same job inline', async () => {
    const onRetryJob = vi.fn()
    const failed = job({ status: 'failed', error_code: 'vendor_failed', error_text: 'The voice service did not answer.', retryable: true })
    doc({ items: [item({ status: 'failed', candidate: null, error: 'older' })], activity: { jobs: [failed], video: null, rendering: null, onRetryJob } })
    const row = screen.getByRole('listitem', { name: /Line at 0:07/ })
    expect(within(row).getByTestId('row-chip')).toHaveTextContent('Failed')
    expect(within(row).getByTestId('failed-reason')).toHaveTextContent('The voice service did not answer.')
    await userEvent.click(within(row).getByRole('button', { name: 'Retry' }))
    expect(onRetryJob).toHaveBeenCalledWith(expect.objectContaining({ job_id: 'J1' }))
  })

  it('a kept line is In the video only when the playing render carries it', () => {
    const rev = { edit_id: 'e1', start: 7.54, end: 9.02, text: 'Start a live Bhaji Cam session.', mix: 'replace' as const }
    const { rerender } = render(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} revisions={[rev]} activity={{ jobs: [], video: { ...none, edit_ids: ['e1'] }, rendering: null }} />)
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('In the video')
    rerender(<LineDoc statements={STATEMENTS} currentTime={0} {...handlers()} revisions={[rev]} activity={{ jobs: [], video: none, rendering: null }} />)
    expect(screen.getAllByTestId('row-chip')[1]).toHaveTextContent('Ready to hear')
  })

  it('one driver at a time: a line Voltage is voicing cannot be voiced from its form', async () => {
    const running = job({ status: 'running', line_ids: ['i1'] })
    doc({ items: [item({ status: 'planned', candidate: null })], activity: { jobs: [running], video: null, rendering: null } })
    await userEvent.click(screen.getByText('Start a live Bajicam session.'))
    expect(screen.getByTestId('driven-note')).toHaveTextContent('Voltage is voicing these lines. Wait or Stop.')
    expect(screen.getByRole('button', { name: 'Voice it' })).toBeDisabled()
  })

  it('counts the words live and hides the estimate until there are any; the time only when one was measured', async () => {
    doc({ activity: { jobs: [], video: null, rendering: null, etaFor: (chars) => chars * 0.2 } })
    await userEvent.click(screen.getByText('Sure, sir.'))
    const box = screen.getByRole('textbox', { name: 'New wording' })
    await userEvent.clear(box)
    expect(screen.queryByTestId('voice-estimate')).toBeNull()
    await userEvent.type(box, 'Of course')
    expect(screen.getByTestId('voice-estimate')).toHaveTextContent('≈ 9 characters · ready in about 2 s')
  })
})

describe('A3: the project words on a line', () => {
  it('marks a take that breaks a word rule, and the user may still add it', async () => {
    const h = doc({ items: [item({ word_rule: { breaks: ['“Bhaji Cam” did not come out as written (the take says “badge cam”).'], warnings: [] } })] })
    const mark = screen.getByTestId('word-rule')
    expect(mark).toHaveTextContent('Breaks a word rule')
    expect(mark).toHaveTextContent('did not come out as written')
    await userEvent.click(screen.getByRole('button', { name: /^Add it/ }))
    expect(h.onAdd).toHaveBeenCalled()
  })

  it('warns about a banned word in a typed line and still voices it', async () => {
    const h = doc({ bannedWords: ['cheap'] })
    const actions = screen.getByRole('group', { name: 'Actions for 0:07' })
    await userEvent.click(within(actions).getByRole('button', { name: 'Edit it' }))
    const box = screen.getByRole('textbox', { name: 'New wording' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Cheap groceries, live now.')
    expect(screen.getByTestId('banned-warning')).toHaveTextContent('“cheap” is a banned word in this project. You can still voice it.')
    await userEvent.keyboard('{Enter}')
    expect(h.onHear).toHaveBeenCalledWith(KEY, expect.objectContaining({ text: 'Cheap groceries, live now.' }))
  })

  it('says nothing for a word that only contains a banned one', async () => {
    doc({ bannedWords: ['cheap'] })
    const actions = screen.getByRole('group', { name: 'Actions for 0:07' })
    await userEvent.click(within(actions).getByRole('button', { name: 'Edit it' }))
    const box = screen.getByRole('textbox', { name: 'New wording' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Cheaply done.')
    expect(screen.queryByTestId('banned-warning')).toBeNull()
  })
})

describe('LineDoc: the simple view (run 5 item 5)', () => {
  const arranged: ArrangementView = {
    arrangement: EMPTY, duration: 12, overrun: 0, ease_ok: true, min_gap_default: 0.15, can_undo: false,
    lines: place(specs(STATEMENTS), EMPTY).map((p, i) => ({ ...p, index: i + 1, text: STATEMENTS[i].text, speaker: STATEMENTS[i].speaker, orig_start: STATEMENTS[i].start, orig_end: STATEMENTS[i].end, length: STATEMENTS[i].end - STATEMENTS[i].start, gap: 0, replaced_by: null })),
  }
  it('has no counts, no timing bar and no "Original" on untouched lines; a proposal keeps its chip and verbs', () => {
    doc({ simple: true, items: [item()], arranged, onArrange: vi.fn() })
    expect(screen.queryByTestId('counts')).toBeNull()
    expect(screen.queryByTestId('arrange-bar')).toBeNull()
    expect(screen.queryByText('3 lines')).toBeNull()
    expect(screen.getAllByTestId('row-chip').map((c) => c.textContent)).toEqual(['Ready to hear'])
    expect(screen.getByRole('button', { name: /Add it/ })).toBeInTheDocument()
  })

  it('under More controls the counts, the timing bar and every chip are back', () => {
    doc({ items: [item()], arranged, onArrange: vi.fn() })
    expect(screen.getByTestId('counts')).toBeInTheDocument()
    expect(screen.getByTestId('arrange-bar')).toBeInTheDocument()
    expect(screen.getAllByTestId('row-chip').map((c) => c.textContent)).toEqual(['Original', 'Ready to hear', 'Original'])
  })
})
