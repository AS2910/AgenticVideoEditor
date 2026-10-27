import { describe, expect, it } from 'vitest'
import type { Candidate } from '../types'
import { takeFacts } from './facts'

const art = { kind: 'audio', sha256: 'a', path: '/a.wav', duration: 1, container: 'wav' }

function take(notes: string[], distance: number | null, measured: string[] = ['prosody', 'prosody_distance']): Candidate {
  return {
    candidate_id: 'c1',
    plan: { selection: { start: 0, end: 1 }, new_text: 'x', voice_profile_id: 'v' },
    audio: art, frames: { ...art, kind: 'video' },
    continuity: { voice_match: null, prosody: 0.9, audio_integration: 0.9, lip_sync: null, prosody_distance: distance, passed: true, warnings: [], measured },
    fit_notes: notes,
  } as unknown as Candidate
}

describe('takeFacts, run 5 item 7', () => {
  it('shows the delivery distance against its bar', () => {
    const close = takeFacts(take([], 0.42)).measured.find((f) => f.label === 'Delivery')
    expect(close).toEqual({ label: 'Delivery', value: 'Delivery 0.42 off · wants under 1.00', tone: 'ok' })
    expect(takeFacts(take([], 1.6)).measured.find((f) => f.label === 'Delivery')?.tone).toBe('needs')
    expect(takeFacts(take([], 0.4, ['prosody'])).measured.find((f) => f.label === 'Delivery')).toBeUndefined()
  })

  it('says a take followed the speaker in its dials, not its fit', () => {
    const steered = takeFacts(take(['delivery matched to the speaker: stability 0.35', 'trimmed 80 ms of pauses'], null))
    expect(steered.grid.find((f) => f.label === 'Dials')?.value).toBe('matched to the speaker')
    expect(steered.grid.find((f) => f.label === 'Fit')?.value).toBe('Trimmed 80 ms of pauses')
    const original = takeFacts(take(["spoken from the original line's delivery"], null))
    expect(original.grid.find((f) => f.label === 'Dials')?.value).toBe('the original line, new voice')
    expect(original.grid.find((f) => f.label === 'Fit')?.value).toBe('Pauses first')
  })
})
