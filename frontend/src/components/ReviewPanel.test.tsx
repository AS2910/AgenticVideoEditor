import { describe, it, expect, vi } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReviewPanel } from './ReviewPanel'
import type { Candidate, Plan, PlanItem } from '../types'

const AUDIO = { kind: 'audio' as const, sha256: 'a'.repeat(64), duration: 0.5, container: 'wav' }
const take = (id: string): Candidate => ({
  candidate_id: id, plan: { selection: { start: 0, end: 0.5 }, new_text: 'Thirty off.', voice_profile_id: 'v', fit: null, mix: 'replace' },
  audio: AUDIO, frames: { ...AUDIO, kind: 'video', container: 'mp4' },
  continuity: { voice_match: null, prosody: 0.93, audio_integration: 0.9, lip_sync: null, passed: true, warnings: [], measured: [] },
})
const item = (id: string, start: number, status: PlanItem['status'] = 'ready'): PlanItem => ({
  item_id: id, selection: { start, end: start + 0.5 }, old_text: 'Twenty off.', new_text: 'Thirty off.', speaker: 'A',
  mix: 'replace', reason: '', kind: 'planned', enabled: true, status, candidate: take(`c-${id}`), edit_id: status === 'approved' ? `e-${id}` : null,
  question: null, error: null, note: null, progress: null, fit: null,
})
const plan = (items: PlanItem[]): Plan => ({
  plan_id: 'plan1', goal: 'g', summary: 's', mode: 'ask', status: 'done', created_at: '', estimate: { items: 2, voice_characters: 20, usd: 0.01, seconds: 1 },
  findings: [], question: null, spend_usd: 0.01, log: [], items,
})

function handlers() {
  return {
    onCompare: vi.fn(), onStop: vi.fn(), onPlayTake: vi.fn(), onRedo: vi.fn(), onUndo: vi.fn(), onDecide: vi.fn(),
    isHeld: () => false, speakers: [{ label: 'A', name: 'Brian', voice_id: null }], playingTake: null, seam: null,
  }
}

describe('ReviewPanel (the polish pass: a player and keys on every row)', () => {
  it('Play the seam becomes Stop while its seam plays, with a progress line along the row', async () => {
    const user = userEvent.setup()
    const h = handlers()
    const p = plan([item('i1', 0), item('i2', 1.5)])
    const { rerender } = render(<ReviewPanel plan={p} {...h} />)
    const [first, second] = screen.getAllByTestId('review-row')
    await user.click(within(first).getByRole('button', { name: 'Play the seam at 0:00' }))
    expect(h.onCompare).toHaveBeenCalledWith(p.items[0])

    rerender(<ReviewPanel plan={p} {...h} seam={{ itemId: 'i1', from: 0, until: 2, now: 1 }} />)
    const stop = within(first).getByRole('button', { name: 'Stop the seam at 0:00' })
    expect(stop).toHaveAttribute('aria-pressed', 'true')
    expect(within(first).getByTestId('seam-progress').firstElementChild).toHaveStyle({ transform: 'scaleX(0.5)' })
    expect(within(second).queryByTestId('seam-progress')).not.toBeInTheDocument()
    expect(within(second).getByRole('button', { name: 'Play the seam at 0:01' })).toBeInTheDocument()
    await user.click(stop)
    expect(h.onStop).toHaveBeenCalled()
  })

  it('Hear the take plays the take alone and says Stop while it plays', async () => {
    const user = userEvent.setup()
    const h = handlers()
    const p = plan([item('i1', 0)])
    const { rerender } = render(<ReviewPanel plan={p} {...h} />)
    await user.click(screen.getByRole('button', { name: 'Hear the take at 0:00 alone' }))
    expect(h.onPlayTake).toHaveBeenCalledWith(p.items[0].candidate)
    rerender(<ReviewPanel plan={p} {...h} playingTake="c-i1" />)
    expect(screen.getByRole('button', { name: 'Stop the take at 0:00' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('button', { name: /^Play the seam/ })).toBeInTheDocument()   // the seam still has its own button
  })

  it('answers the keys on a focused row: ↑↓ move, Space plays the seam, T hears the take, K keeps, H holds, A another take, U undoes', async () => {
    const user = userEvent.setup()
    const h = handlers()
    const p = plan([item('i1', 0), item('i2', 1.5, 'approved')])
    render(<ReviewPanel plan={p} {...h} />)
    const [first, second] = screen.getAllByTestId('review-row')
    expect(screen.getByTestId('review-keys')).not.toBeVisible()
    act(() => first.focus())
    expect(screen.getByTestId('review-keys')).toBeVisible()
    expect(screen.getByTestId('review-keys')).toHaveTextContent('K keep · H hold · A another take · U undo')

    await user.keyboard(' ')
    expect(h.onCompare).toHaveBeenCalledWith(p.items[0])
    await user.keyboard('t')
    expect(h.onPlayTake).toHaveBeenCalledWith(p.items[0].candidate)
    await user.keyboard('k')
    expect(h.onDecide).toHaveBeenLastCalledWith(p.items[0], true)
    await user.keyboard('h')
    expect(h.onDecide).toHaveBeenLastCalledWith(p.items[0], false)
    await user.keyboard('a')
    expect(h.onRedo).toHaveBeenCalledWith(p.items[0])
    await user.keyboard('u')   // not shipped: nothing to undo
    expect(h.onUndo).not.toHaveBeenCalled()

    await user.keyboard('{ArrowDown}')
    expect(second).toHaveFocus()
    await user.keyboard('u')
    expect(h.onUndo).toHaveBeenCalledWith(p.items[1])
    await user.keyboard('k')   // shipped: Keep/Hold do not apply
    expect(h.onDecide).toHaveBeenCalledTimes(2)
    await user.keyboard('{ArrowUp}')
    expect(first).toHaveFocus()
  })

  it('keys typed inside a row\'s control are left to the control', async () => {
    const user = userEvent.setup()
    const h = handlers()
    render(<ReviewPanel plan={plan([item('i1', 0)])} {...h} />)
    screen.getByRole('button', { name: 'Keep' }).focus()
    await user.keyboard('h')
    expect(h.onDecide).not.toHaveBeenCalled()
  })
})
