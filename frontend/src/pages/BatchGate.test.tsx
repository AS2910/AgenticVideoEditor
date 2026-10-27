import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BatchGate } from './BatchGate'
import type { Batch } from '../types'

const batch = (over: Partial<Batch> = {}): Batch => ({
  batch_id: 'b1', project_id: 'f1', source: 'brief', goal: 'Apply brief changes to v2', phase: 'gate', status: 'waiting', step: '',
  created_at: '2026-10-22T00:00:00.000Z', started_at: null, finished_at: null,
  totals: { videos: 2, lines: 3, est_usd: 0.4, est_s: 60, cap_usd: 1 }, summary: null,
  rows: [{ video_id: 'p1', filename: 'a.mp4', lines: 2 }, { video_id: 'p2', filename: 'b.mp4', lines: 1 }] as Batch['rows'],
  counts: {}, spent_usd: 0, can_add: false, ...over,
})

describe('BatchGate (decision 0)', () => {
  it('says how many approved videos will return to Draft, and Go is the last action', async () => {
    const onGo = vi.fn()
    render(<BatchGate batch={batch({ approved_count: 2, approved_note: '2 approved videos will return to Draft.' })} busy={false} going={false} onGo={onGo} onCancel={vi.fn()} />)
    expect(screen.getByTestId('batch-approved')).toHaveTextContent('2 approved videos will return to Draft.')
    const buttons = screen.getAllByRole('button')
    expect(buttons.at(-1)).toHaveTextContent('Go · 2 videos')
    await userEvent.click(buttons.at(-1)!)
    expect(onGo).toHaveBeenCalled()
  })

  it('says nothing about Draft when no video is approved', () => {
    render(<BatchGate batch={batch()} busy={false} going={false} onGo={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.queryByTestId('batch-approved')).not.toBeInTheDocument()
  })
})
