import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import { Lanes, packRows } from './Lanes'
import type { Candidate, Piece, PlanItem, Revision, Speaker, Statement } from '../types'

const SPEAKERS: Speaker[] = [
  { label: 'A', name: 'Riya', voice_id: null },
  { label: 'B', name: 'Marcus', voice_id: null },
]
const STATEMENTS: Statement[] = [
  { text: 'Hi, I want to buy groceries.', start: 4.0, end: 6.9, speaker: 'A' },
  { text: 'Start a live Bajicam session.', start: 31.0, end: 34.0, speaker: 'B' },
]
const add = (over: Partial<Revision>): Revision => ({ edit_id: `e-${over.start}`, start: 10, end: 13, text: 'Woohoo!', mix: 'layer', ...over })
const candidate = (over: Partial<Candidate['plan']> = {}, duration = 2): Candidate => ({
  candidate_id: 'c1',
  plan: { selection: { start: 20, end: 20 }, new_text: 'And here it is.', voice_profile_id: 'v1', mix: 'layer', ...over },
  audio: { kind: 'audio', sha256: 'a'.repeat(64), duration, container: 'wav' },
  frames: { kind: 'video', sha256: 'f'.repeat(64), duration, container: 'mp4' },
  continuity: { voice_match: null, prosody: 0.96, audio_integration: 0.99, lip_sync: null, passed: true, warnings: [], measured: [] },
})
const item = (over: Partial<PlanItem> = {}): PlanItem => ({
  item_id: 'i1', selection: { start: 20, end: 20 }, old_text: '', new_text: 'And here it is.', speaker: null, mix: 'layer',
  reason: '', kind: 'planned', enabled: true, status: 'ready', fit: null, candidate: candidate(), edit_id: null,
  question: null, error: null, note: null, progress: null, ...over,
})
const base = { duration: 48.9, currentTime: 0, statements: STATEMENTS, speakers: SPEAKERS, revisions: [] as Revision[], items: [] as PlanItem[] }

describe('Lanes: coexisting audio is seen as such', () => {
  it('lays three added lines over the same seconds in three sub-rows, one pill each', () => {
    const revisions = [
      add({ start: 10, end: 13, text: 'Woohoo!' }),
      add({ start: 10.5, end: 12, text: 'Yes!' }),
      add({ start: 11, end: 14, text: 'Go go go' }),
    ]
    render(<Lanes {...base} revisions={revisions} onSeek={() => {}} />)
    const a2 = within(screen.getByTestId('lane-a2'))
    const subs = a2.getAllByTestId('sublane')
    expect(subs).toHaveLength(3)
    expect(subs.map((s) => within(s).getAllByRole('button').length)).toEqual([1, 1, 1])
    expect(a2.getByRole('button', { name: 'Added line at 0:10: Woohoo!' })).toBeInTheDocument()
    expect(a2.getByRole('button', { name: 'Added line at 0:10: Yes!' })).toBeInTheDocument()
    expect(a2.getByRole('button', { name: 'Added line at 0:11: Go go go' })).toBeInTheDocument()
    // Each is placed by its own seconds, nothing collapsed.
    const first = a2.getByRole('button', { name: 'Added line at 0:10: Woohoo!' })
    expect(first.style.left).toBe(`${(10 / 48.9) * 100}%`)
  })

  it('packs lines that do not overlap into one sub-row', () => {
    const rows = packRows([{ start: 0, end: 2 }, { start: 2, end: 4 }, { start: 1, end: 3 }])
    expect(rows.map((r) => r.map((s) => s.start))).toEqual([[0, 2], [1]])
  })

  it('reads a removed line as removed and lays a room-tone patch under it', () => {
    render(<Lanes {...base} revisions={[{ edit_id: 'r1', start: 31, end: 34, text: '', mix: 'remove' }]} onSeek={() => {}} />)
    const removed = screen.getByRole('button', { name: 'Removed line at 0:31, Marcus' })
    expect(removed).toHaveClass('line-through')
    expect(removed).toHaveAttribute('data-state', 'removed')
    const a3 = within(screen.getByTestId('lane-a3'))
    expect(a3.getByRole('button', { name: 'Room tone at 0:31' })).toHaveTextContent('Tone patch')
    expect(screen.getByRole('button', { name: 'Spoken line at 0:04, Riya' })).not.toHaveClass('line-through')
  })

  it('hides the tone lane when nothing was removed, and says when nothing is added', () => {
    render(<Lanes {...base} onSeek={() => {}} />)
    expect(screen.queryByTestId('lane-a3')).toBeNull()
    expect(within(screen.getByTestId('lane-a2')).getByText('Nothing added yet')).toBeInTheDocument()
    expect(screen.getByTestId('lanes')).toHaveAttribute('aria-label', 'Lanes')
  })

  it('lights a spoken line a replacement changed, with the new words', () => {
    render(<Lanes {...base} revisions={[{ edit_id: 'r2', start: 31, end: 34, text: 'Start a live Bhaji Cam session.', mix: 'replace' }]} onSeek={() => {}} />)
    const changed = screen.getByRole('button', { name: 'Changed line at 0:31, Marcus: Start a live Bhaji Cam session.' })
    expect(changed).toHaveClass('border-ink', 'bg-volt')   // Volt: a change is volt with ink
    expect(changed).toHaveAttribute('title', 'Start a live Bhaji Cam session.')
  })
})

describe('Lanes: the picture', () => {
  it('labels a flexed piece by its percentage and a held frame by its seconds', () => {
    const pieces: Piece[] = [
      { start: 0, end: 14, out_start: 0, out_end: 14, kind: 'copy', factor: null },
      { start: 14, end: 20, out_start: 14, out_end: 20.48, kind: 'flex', factor: 1.08 },
      { start: 20, end: 20, out_start: 20.48, out_end: 21.08, kind: 'hold', factor: null },
      { start: 20, end: 30, out_start: 21.08, out_end: 30.28, kind: 'flex', factor: 0.92 },
      { start: 30, end: 48.9, out_start: 30.28, out_end: 49.18, kind: 'copy', factor: null },
    ]
    render(<Lanes {...base} pieces={pieces} onSeek={() => {}} />)
    const v1 = within(screen.getByTestId('lane-v1'))
    expect(v1.getByRole('button', { name: 'Picture flexed +8% at 0:14' })).toHaveTextContent('Flexed +8%')
    expect(v1.getByRole('button', { name: 'Picture held 0.6 s at 0:20' })).toHaveTextContent('Held 0.6 s')
    expect(v1.getByRole('button', { name: 'Picture flexed −8% at 0:20' })).toHaveTextContent('Flexed −8%')
    expect(v1.getAllByRole('button', { name: /^Picture as shot/ })).toHaveLength(2)
    // A held frame has no span of its own; it still gets a sliver to be seen and clicked.
    expect(parseFloat(v1.getByRole('button', { name: 'Picture held 0.6 s at 0:20' }).style.width)).toBeGreaterThan(0)
  })

  it('shows the picture as shot when there are no pieces', () => {
    render(<Lanes {...base} onSeek={() => {}} />)
    expect(within(screen.getByTestId('lane-v1')).getByRole('button', { name: 'Picture as shot at 0:00' })).toHaveTextContent('As shot')
  })
})

describe('Lanes: seeking and placing', () => {
  it('seeks to a pill\'s start when it is clicked, and from the ruler\'s slider', () => {
    const onSeek = vi.fn()
    render(<Lanes {...base} revisions={[add({ start: 10, end: 13 })]} currentTime={2.5} onSeek={onSeek} />)
    fireEvent.click(screen.getByRole('button', { name: 'Spoken line at 0:04, Riya' }))
    expect(onSeek).toHaveBeenLastCalledWith(4)
    fireEvent.click(screen.getByRole('button', { name: 'Added line at 0:10: Woohoo!' }))
    expect(onSeek).toHaveBeenLastCalledWith(10)
    const seek = screen.getByRole('slider', { name: 'Seek' })
    expect(seek).toHaveAttribute('step', '0.01')
    expect(seek).toHaveAttribute('max', '48.9')
    fireEvent.change(seek, { target: { value: '12.34' } })
    expect(onSeek).toHaveBeenLastCalledWith(12.34)
    expect(screen.getByTestId('head').style.left).toBe(`${(2.5 / 48.9) * 100}%`)
  })

  it('shows the take being placed as a slider in A2, nudged with the arrow keys', () => {
    const onPlace = vi.fn()
    render(<Lanes {...base} duration={10} placing={{ start: 2, duration: 1 }} onPlace={onPlace} onSeek={() => {}} />)
    const block = within(screen.getByTestId('lane-a2')).getByRole('slider', { name: 'Where the take starts' })
    expect(block).toHaveAttribute('aria-valuenow', '2')
    expect(block).toHaveAttribute('aria-valuemin', '0')
    expect(block).toHaveAttribute('aria-valuemax', '10')
    expect(block.style.left).toBe('20%')
    expect(block.style.width).toBe('10%')
    block.focus()
    fireEvent.keyDown(block, { key: 'ArrowRight' })
    expect(onPlace).toHaveBeenCalledWith(2.1)
    fireEvent.keyDown(block, { key: 'ArrowLeft', shiftKey: true })
    expect(onPlace).toHaveBeenCalledWith(1)
    // The placing row is not one of the packed sub-rows.
    expect(within(screen.getByTestId('lane-a2')).queryAllByTestId('sublane')).toHaveLength(0)
  })
})

describe('Lanes: levels, proposals, names', () => {
  it('tags a line mixed in the background with its level', () => {
    render(<Lanes {...base} revisions={[add({ start: 10, end: 13, text: 'Crowd noise', level_db: -12 })]} onSeek={() => {}} />)
    const pill = screen.getByRole('button', { name: 'Added line at 0:10: Crowd noise' })
    expect(within(pill).getByTestId('level')).toHaveTextContent('−12 dB')
    expect(pill).toHaveAttribute('title', 'Crowd noise')
  })

  it('leaves a foreground line untagged', () => {
    render(<Lanes {...base} revisions={[add({ start: 10, end: 13, level_db: 0 })]} onSeek={() => {}} />)
    expect(screen.queryByTestId('level')).toBeNull()
  })

  it('shows a proposed line in the changed tone, a working one with a pulse, a stuck one as needing you', () => {
    const items = [
      item({ item_id: 'i1', status: 'ready' }),
      item({ item_id: 'i2', status: 'working', candidate: null, selection: { start: 25, end: 25 }, new_text: 'Still voicing' }),
      item({ item_id: 'i3', status: 'needs-you', candidate: candidate({ selection: { start: 30, end: 30 }, new_text: 'Help me', level_db: -12 }) }),
      item({ item_id: 'i4', status: 'dismissed', candidate: candidate({ selection: { start: 40, end: 40 }, new_text: 'Gone' }) }),
      item({ item_id: 'i5', status: 'ready', mix: 'replace', selection: { start: 31, end: 34 }, new_text: 'Replaced words', candidate: candidate({ selection: { start: 31, end: 34 }, new_text: 'Replaced words', mix: 'replace' }) }),
    ]
    render(<Lanes {...base} items={items} onSeek={() => {}} />)
    const a2 = within(screen.getByTestId('lane-a2'))
    const proposed = a2.getByRole('button', { name: 'Proposed line at 0:20: And here it is.' })
    expect(proposed).toHaveClass('border-ink', 'bg-volt', 'text-ink')
    // The span is the take's own length from where it starts.
    expect(proposed.style.width).toBe(`${(2 / 48.9) * 100}%`)
    const voicing = a2.getByRole('button', { name: 'Voicing line at 0:25: Still voicing' })
    expect(within(voicing).getByTestId('pulse')).toHaveClass('animate-pulse')
    const needs = a2.getByRole('button', { name: 'Line needing you at 0:30: Help me' })
    expect(needs).toHaveClass('border-ink', 'bg-warn', 'text-ink')
    expect(within(needs).getByTestId('level')).toHaveTextContent('−12 dB')
    expect(a2.queryByRole('button', { name: /Gone/ })).toBeNull()
    // A replace item marks its spoken line, not A2.
    expect(a2.queryByRole('button', { name: /Replaced words/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Changed line at 0:31, Marcus: Replaced words' })).toBeInTheDocument()
  })

  it('names an unnamed speaker by order of appearance', () => {
    const speakers: Speaker[] = [{ label: 'A', name: '', voice_id: null }, { label: 'B', name: '', voice_id: null }]
    render(<Lanes {...base} speakers={speakers} onSeek={() => {}} />)
    expect(screen.getByRole('button', { name: 'Spoken line at 0:04, Speaker 1' })).toHaveTextContent('Speaker 1 0:04')
    expect(screen.getByRole('button', { name: 'Spoken line at 0:31, Speaker 2' })).toHaveTextContent('Speaker 2 0:31')
  })

  it('hides A1 on a clip with no speech and keeps V1 and A2', () => {
    render(<Lanes {...base} statements={[]} onSeek={() => {}} />)
    expect(screen.queryByTestId('lane-a1')).toBeNull()
    expect(screen.getByTestId('lane-v1')).toBeInTheDocument()
    expect(screen.getByTestId('lane-a2')).toBeInTheDocument()
  })
})
