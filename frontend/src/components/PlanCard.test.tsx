import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PlanCard } from './PlanCard'
import type { Plan, PlanItem } from '../types'

const SPEAKERS = [
  { label: 'A', name: 'Customer', voice_id: null },
  { label: 'B', name: 'Shopkeeper', voice_id: 'nPczCjzI2devNBz1zQrb' },
]
const VOICES = [{ voice_id: 'nPczCjzI2devNBz1zQrb', name: 'Brian', description: '', gender: 'male', accent: null, age: null }]

const item = (over: Partial<PlanItem> = {}): PlanItem => ({
  item_id: 'i1', selection: { start: 7.54, end: 9.02 }, old_text: 'Start a live Bajicam session.',
  new_text: 'Start a live Bhaji Cam session.', speaker: 'A', mix: 'replace', reason: 'Brand name',
  kind: 'planned', enabled: true, status: 'planned', fit: null, candidate: null, edit_id: null,
  question: null, error: null, note: null, progress: null, ...over,
})

const CANDIDATE = {
  candidate_id: 'c1',
  plan: { selection: { start: 7.54, end: 9.02 }, new_text: 'Start a live Bhaji Cam session.', voice_profile_id: 'nPczCjzI2devNBz1zQrb' },
  audio: { kind: 'audio' as const, sha256: 'a'.repeat(64), duration: 1.5, container: 'wav' },
  frames: { kind: 'video' as const, sha256: 'f'.repeat(64), duration: 1.5, container: 'mp4' },
  continuity: { voice_match: null, prosody: 0.96, audio_integration: 0.99, lip_sync: null, passed: true, warnings: [], measured: ['prosody', 'audio_integration'] },
}

const plan = (over: Partial<Plan> = {}): Plan => ({
  plan_id: 'plan1', goal: 'Say Bhaji Cam', summary: 'One change does it.', mode: 'ask', status: 'proposed',
  created_at: '2026-10-02T10:00:00Z', estimate: { items: 1, voice_characters: 31, usd: 0.0093, seconds: 12 },
  findings: [], question: null, spend_usd: 0, log: [], items: [item()], ...over,
})

const handlers = () => ({ onRedo: vi.fn() })

describe('PlanCard, proposed', () => {
  it('lists each change in words, with who says it and why — nothing to tick, type or run', () => {
    render(<PlanCard plan={plan()} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} onAdjust={() => {}} />)
    expect(screen.getByText('1 change')).toBeInTheDocument()
    expect(screen.getByText('Customer, 0:07')).toBeInTheDocument()
    expect(screen.getByText('Say “Start a live Bhaji Cam session.” at 0:07')).toBeInTheDocument()
    expect(screen.getByText('Brand name')).toBeInTheDocument()
    // Every change to the plan is said to Voltage; the card has no form.
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('button', { name: /go ahead|run|stop|voice the change/i })).toBeNull()
    expect(screen.queryByText(/voice characters/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Adjust' })).toBeInTheDocument()
  })

  it('mentions a suggestion in a sentence until the plan has run', () => {
    const noticed = item({ item_id: 'i2', kind: 'suggestion', enabled: false, status: 'suggested',
      selection: { start: 23.4, end: 24.8 }, speaker: 'B', old_text: 'These are regular ones.', new_text: 'These are everyday ones.' })
    render(<PlanCard plan={plan({ items: [item(), noticed] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    expect(screen.getByText(/I also noticed/)).toHaveTextContent('“These are regular ones.” at 0:23. I\'ll ask about it after this one')
    expect(screen.queryByTestId('suggestion')).not.toBeInTheDocument()
  })

  it('puts a suggestion after the plan has run, as a question for the box — no buttons', () => {
    const noticed = item({ item_id: 'i2', kind: 'suggestion', enabled: false, status: 'suggested',
      selection: { start: 23.4, end: 24.8 }, speaker: 'B', old_text: 'These are regular ones.',
      new_text: 'These are everyday ones.', reason: 'Reads oddly in a sale ad' })
    render(<PlanCard plan={plan({ status: 'done', items: [item({ status: 'ready', candidate: CANDIDATE }), noticed] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    const box = screen.getByTestId('suggestion')
    const wrap = screen.getByTestId('plan').parentElement as HTMLElement
    expect(Array.from(wrap.children).map((c) => c.getAttribute('data-testid'))).toEqual(['plan', 'suggestion'])
    expect(box).toHaveTextContent('Noticed: at 0:23 Shopkeeper says “These are regular ones.”, reads oddly in a sale ad. Change it to “These are everyday ones.”?')
    expect(within(box).queryByRole('button')).toBeNull()
  })
})

describe('PlanCard, running and done', () => {
  it('shows a ready take with its score and Another take; what you do next is not the plan\'s', async () => {
    const h = handlers()
    const items = [item({ status: 'ready', candidate: CANDIDATE }), item({ item_id: 'i2', status: 'working', selection: { start: 9.38, end: 9.88 }, speaker: 'B' })]
    render(<PlanCard plan={plan({ status: 'running', items })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    expect(screen.getByText('1 of 2 done')).toBeInTheDocument()
    expect(screen.getByText("Said “Start a live Bhaji Cam session.” at 0:07, in the Customer's own voice.")).toBeInTheDocument()
    expect(screen.getByText("Take · Brian's voice")).toBeInTheDocument()
    expect(screen.getByText('0.96')).toBeInTheDocument()
    expect(screen.getByLabelText('Play take')).toHaveAttribute('src', `/api/projects/p1/artifacts/${'a'.repeat(64)}`)
    expect(screen.getByText('Starting…')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Another take' }))
    expect(h.onRedo).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
    // What you do next (review, ship) is the panel's own last card (ShipCard), not the plan's.
    expect(screen.queryByTestId('next-action')).toBeNull()
  })

  it('narrates what is happening to a line while it is voiced', () => {
    const working = item({ status: 'working', progress: 'Take 1: pitch is -6.3 semitones off the surrounding speech. Trying again (take 2 of 3)' })
    render(<PlanCard plan={plan({ status: 'running', items: [working] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    expect(screen.getByTestId('narration')).toHaveTextContent('Take 1: pitch is -6.3 semitones off')
  })

  it('says what a line needs you for, in words; the answer goes in the box', () => {
    const needs = item({ status: 'needs-you', question: {
      type: 'question', question: "The new line runs 1.1 s long and there's no pause after it to run into.",
      text: 'x', mix: 'replace',
      options: [
        { label: 'Use a shorter line: “Two kinds, both on sale.”', fit: null, mix: null, warning: null, text: 'Two kinds, both on sale.' },
        { label: 'Speed it up to fit (1.3× speed)', fit: 'stretch', mix: null, warning: 'It will sound rushed.' },
      ],
    } })
    render(<PlanCard plan={plan({ status: 'done', items: [needs] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    expect(screen.getByTestId('needs-you')).toHaveTextContent('runs 1.1 s long')
    expect(screen.queryByRole('button', { name: /shorter line|speed it up/i })).toBeNull()
  })

  it('offers Redo for a failed line', async () => {
    const h = handlers()
    render(<PlanCard plan={plan({ status: 'done', items: [item({ status: 'failed', error: 'Generation failed after several attempts. Redo to try again.' })] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    await userEvent.click(screen.getByRole('button', { name: 'Redo' }))
    expect(h.onRedo).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }))
  })
})

describe('PlanCard, proposed again after a take', () => {
  it('shows a voiced item with its take and says it keeps it', () => {
    const voiced = item({ status: 'ready', candidate: CANDIDATE })
    const reworded = item({ item_id: 'i2', selection: { start: 9.38, end: 9.88 }, speaker: 'B', new_text: 'Thirty off.', note: 'Reworded as you asked' })
    render(<PlanCard plan={plan({ items: [voiced, reworded] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    expect(screen.getByText('2 changes · 2 speakers · 1 voiced')).toBeInTheDocument()
    expect(screen.getByText(/Already voiced; it keeps this take/)).toBeInTheDocument()
    expect(screen.getByLabelText('Play take')).toBeInTheDocument()
    expect(screen.getByText('Reworded as you asked')).toBeInTheDocument()
  })
})

describe('PlanCard, empty (UX-4)', () => {
  it('says when a goal changes nothing, instead of an empty list', () => {
    render(<PlanCard plan={plan({ items: [], summary: 'No line mentions the offer.' })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    expect(screen.getByTestId('plan-empty')).toHaveTextContent('Nothing to change for that. No line mentions the offer.')
  })
})

describe('the plan\'s voice (15e)', () => {
  const VOICES2 = [
    ...VOICES,
    { voice_id: 'kL06KYMvPY56NluIQ72m', name: 'Varsha', description: 'Warm and Clear', gender: 'female', accent: 'indian', age: 'middle_aged' },
  ]

  it('names the voice the goal asked for, with the planner\'s note, and lets you change it', async () => {
    const h = handlers()
    const onVoice = vi.fn()
    render(<PlanCard plan={plan({ voice: 'kL06KYMvPY56NluIQ72m', voice_asked: true, voice_note: "Varsha's voice: Indian, warm and clear." })} speakers={SPEAKERS} voices={VOICES2} projectId="p1" {...h} onVoice={onVoice} />)
    const row = screen.getByTestId('plan-voice')
    expect(within(row).getByText('Varsha')).toBeInTheDocument()
    expect(within(row).getByText('female, indian')).toBeInTheDocument()
    expect(within(row).getByText("Varsha's voice: Indian, warm and clear.")).toBeInTheDocument()
    await userEvent.click(within(row).getByRole('button', { name: 'Change' }))
    await userEvent.selectOptions(within(row).getByRole('combobox', { name: "The plan's voice" }), 'nPczCjzI2devNBz1zQrb')
    expect(onVoice).toHaveBeenCalledWith('nPczCjzI2devNBz1zQrb')
  })

  it('says plainly when nothing fit, and shows no voice row when the goal said nothing about it', () => {
    const { unmount } = render(<PlanCard plan={plan({ voice: null, voice_asked: false, voice_note: 'No Indian voice is on the list yet, so I kept the default voice.' })} speakers={SPEAKERS} voices={VOICES2} projectId="p1" {...handlers()} />)
    expect(within(screen.getByTestId('plan-voice')).getByText('the default')).toBeInTheDocument()
    expect(within(screen.getByTestId('plan-voice')).getByText('No Indian voice is on the list yet, so I kept the default voice.')).toBeInTheDocument()
    unmount()
    render(<PlanCard plan={plan()} speakers={SPEAKERS} voices={VOICES2} projectId="p1" {...handlers()} />)
    expect(screen.queryByTestId('plan-voice')).toBeNull()
  })
})
