import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UpNext } from './UpNext'
import type { QueueItem } from '../types'

/** Up next (2026-10-25): the changes waiting on a busy video, in order, under the status strip. */

const item = (id: number, label: string, status: QueueItem['status'] = 'queued'): QueueItem => ({
  id, video_id: 'p1', kind: 'action', label, payload: { op: 'add' }, position: id, created_by: 'local', status,
})
const handlers = () => ({ onRemove: vi.fn(), onReorder: vi.fn(), onRunNext: vi.fn(), onClear: vi.fn() })

describe('Up next', () => {
  it('shows nothing when nothing waits', () => {
    render(<UpNext items={[]} paused={false} {...handlers()} />)
    expect(screen.queryByTestId('up-next')).toBeNull()
  })

  it('lists the changes in order, each with an x, and Alt+arrow moves one', async () => {
    const h = handlers()
    render(<UpNext items={[item(1, 'Add line 3', 'running'), item(2, 'Discard line 4'), item(3, 'Make it warmer')]} paused={false} {...h} />)
    expect(screen.getAllByTestId('up-next-chip').map((c) => c.textContent)).toEqual(['Now: Add line 3', 'Discard line 4', 'Make it warmer'])
    expect(screen.queryByRole('button', { name: 'Remove Add line 3 from Up next' })).toBeNull()      // running: it stays
    await userEvent.click(screen.getByRole('button', { name: 'Remove Discard line 4 from Up next' }))
    expect(h.onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
    screen.getByLabelText(/^2 of 2: Make it warmer/).focus()
    await userEvent.keyboard('{Alt>}{ArrowLeft}{/Alt}')
    expect(h.onReorder).toHaveBeenCalledWith([3, 2])
    expect(screen.queryByTestId('run-next')).toBeNull()
  })

  it('paused after a failure or a Stop: Run next, or Clear queue', async () => {
    const h = handlers()
    render(<UpNext items={[item(2, 'Add line 2')]} paused {...h} />)
    expect(screen.getByTestId('up-next')).toHaveTextContent('Up next · paused')
    await userEvent.click(screen.getByTestId('run-next'))
    await userEvent.click(screen.getByTestId('clear-queue'))
    expect(h.onRunNext).toHaveBeenCalledOnce()
    expect(h.onClear).toHaveBeenCalledOnce()
  })

  it('another tab or member reads it and changes nothing', () => {
    render(<UpNext items={[item(2, 'Add line 2')]} paused readOnly {...handlers()} />)
    expect(screen.getByTestId('up-next-chip')).toHaveTextContent('Add line 2')
    expect(screen.queryByRole('button')).toBeNull()
  })
})
