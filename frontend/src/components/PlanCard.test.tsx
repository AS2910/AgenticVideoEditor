import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PlanCard } from './PlanCard'
import { estimateText } from '../transcript/planText'
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
  question: null, error: null, note: null, ...over,
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
  log: [], items: [item()], ...over,
})

const handlers = () => ({
  onToggle: vi.fn(), onReword: vi.fn(), onInclude: vi.fn(), onRun: vi.fn(), onAnswer: vi.fn(), onRedo: vi.fn(), onApproveAll: vi.fn(),
})

describe('PlanCard, proposed', () => {
  it('lists each change ticked and editable, with the estimate and Run', async () => {
    const h = handlers()
    render(<PlanCard plan={plan()} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    expect(screen.getByText('1 change')).toBeInTheDocument()
    expect(screen.getByText('Customer, 0:07')).toBeInTheDocument()
    expect(screen.getByText('Brand name')).toBeInTheDocument()
    expect(screen.getByText('About 31 voice characters and under $0.01. Ready in about 12 seconds.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Include the change at 0:07' }))
    expect(h.onToggle).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }), false)

    const box = screen.getByRole('textbox', { name: 'New wording at 0:07' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Start a Bhaji Cam session.{Enter}')
    expect(h.onReword).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }), 'Start a Bhaji Cam session.')

    await userEvent.click(screen.getByRole('button', { name: 'Run 1 change' }))
    expect(h.onRun).toHaveBeenCalled()
  })

  it('disables Run with nothing ticked', () => {
    render(<PlanCard plan={plan({ items: [item({ enabled: false })] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...handlers()} />)
    expect(screen.getByRole('button', { name: 'Run 0 changes' })).toBeDisabled()
  })

  it('offers a suggestion to add or leave', async () => {
    const h = handlers()
    const noticed = item({ item_id: 'i2', kind: 'suggestion', enabled: false, status: 'suggested',
      selection: { start: 23.4, end: 24.8 }, speaker: 'B', old_text: 'These are regular ones.',
      new_text: 'These are everyday ones.', reason: 'Reads oddly in a sale ad' })
    render(<PlanCard plan={plan({ items: [item(), noticed] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    const box = screen.getByTestId('suggestion')
    expect(box).toHaveTextContent('Noticed: at 0:23 Shopkeeper says “These are regular ones.”, reads oddly in a sale ad. Change it to “These are everyday ones.”?')
    await userEvent.click(within(box).getByRole('button', { name: 'Add to plan' }))
    expect(h.onInclude).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i2' }), true)
    await userEvent.click(within(box).getByRole('button', { name: 'Leave it' }))
    expect(h.onInclude).toHaveBeenLastCalledWith(expect.objectContaining({ item_id: 'i2' }), false)
  })
})

describe('PlanCard, running', () => {
  it('shows progress, a ready take with its score, and Approve', async () => {
    const h = handlers()
    const items = [item({ status: 'ready', candidate: CANDIDATE }), item({ item_id: 'i2', status: 'working', selection: { start: 9.38, end: 9.88 }, speaker: 'B' })]
    render(<PlanCard plan={plan({ status: 'running', items })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    expect(screen.getByText('1 of 2 ready')).toBeInTheDocument()
    expect(screen.getByText("Take, Brian's voice")).toBeInTheDocument()
    expect(screen.getByText('0.96')).toBeInTheDocument()
    expect(screen.getByLabelText('Play take')).toHaveAttribute('src', `/api/projects/p1/artifacts/${'a'.repeat(64)}`)
    expect(screen.getByText('Voicing the line…')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Approve 1 ready change' }))
    expect(h.onApproveAll).toHaveBeenCalled()
  })

  it("puts the agent's own fix first when a line needs you", async () => {
    const h = handlers()
    const needs = item({ status: 'needs-you', question: {
      type: 'question', question: "The new line runs 1.1 s long and there's no pause after it to run into.",
      text: 'x', mix: 'replace',
      options: [
        { label: 'Use a shorter line: “Two kinds, both on sale.”', fit: null, mix: null, warning: null, text: 'Two kinds, both on sale.' },
        { label: 'Speed it up to fit (1.3× speed)', fit: 'stretch', mix: null, warning: 'It will sound rushed.' },
      ],
    } })
    render(<PlanCard plan={plan({ status: 'done', items: [needs] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    const box = screen.getByTestId('needs-you')
    expect(box).toHaveTextContent('runs 1.1 s long')
    const buttons = within(box).getAllByRole('button')
    expect(buttons[0]).toHaveTextContent('Use a shorter line')
    await userEvent.click(buttons[0])
    expect(h.onAnswer).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'i1' }), expect.objectContaining({ text: 'Two kinds, both on sale.' }))
  })

  it('offers Redo for a failed line', async () => {
    const h = handlers()
    render(<PlanCard plan={plan({ status: 'done', items: [item({ status: 'failed', error: 'Generation failed after several attempts. Redo to try again.' })] })} speakers={SPEAKERS} voices={VOICES} projectId="p1" {...h} />)
    await userEvent.click(screen.getByRole('button', { name: 'Redo' }))
    expect(h.onRedo).toHaveBeenCalled()
  })
})

describe('estimateText', () => {
  it('reads the estimate in words', () => {
    expect(estimateText({ items: 3, voice_characters: 110, usd: 0.033, seconds: 36 })).toBe('About 110 voice characters and about $0.03. Ready in about 36 seconds.')
    expect(estimateText({ items: 6, voice_characters: 400, usd: 0.12, seconds: 72 })).toBe('About 400 voice characters and about $0.12. Ready in about 1 minute.')
    expect(estimateText({ items: 1, voice_characters: 0, usd: 0, seconds: 12 })).toBe('No paid voice. Ready in about 12 seconds.')
  })
})
