import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueuedCard } from './QueuedCard'
import { VoltagePane } from './VoltagePane'
import { UpNext } from './UpNext'
import { QUEUE_CARD_STATES, QUEUE_STATE_WORD, firstWords, queueCardLabel, queueStateLabel } from '../lib/queueState'
import type { ChatMessage, QueueItem } from '../types'

/** Addendum 3.3: messages typed while Working queue clearly, as cards in the thread and chips in Up next. */

const goal = (id: number, text: string, status: QueueItem['status'] = 'queued', error: string | null = null): QueueItem => ({
  id, video_id: 'p1', kind: 'goal', label: text, payload: { text }, position: id, created_by: 'local', status, error,
})

describe('queue state words, in one place', () => {
  it('names the five states a card can show', () => {
    expect(QUEUE_CARD_STATES.map((s) => QUEUE_STATE_WORD[s])).toEqual(['Queued', 'Running', 'Done', 'Stopped', 'Failed'])
  })

  it('counts a waiting message over what still waits, and keeps the first words', () => {
    const live = [goal(1, 'Make the opening warmer', 'running'), goal(2, 'Then make the ending a bit shorter please'), goal(3, 'Louder')]
    expect(queueStateLabel(live[0], live)).toBe('Running')
    expect(queueCardLabel(live[1], live)).toBe('Queued 1 of 2: Then make the ending a bit...')
    expect(queueCardLabel(live[2], live)).toBe('Queued 2 of 2: Louder')
    expect(firstWords('  one   two  ')).toBe('one two')
    expect(queueStateLabel(goal(9, 'x', 'stopped'), live)).toBe('Stopped')
  })
})

describe('QueuedCard', () => {
  it('reads "Queued 1 of 2: <first words>" and offers Edit and Remove while it waits', async () => {
    const live = [goal(1, 'Make it warmer'), goal(2, 'Make it louder')]
    const onEdit = vi.fn().mockResolvedValue(undefined)
    const onRemove = vi.fn()
    render(<QueuedCard item={live[0]} live={live} onEdit={onEdit} onRemove={onRemove} />)
    const card = screen.getByTestId('queued-card')
    expect(card).toHaveAccessibleName('Queued 1 of 2: Make it warmer')
    expect(card.textContent).toContain('Queued 1 of 2: Make it warmer')
    await userEvent.click(screen.getByRole('button', { name: 'Edit Make it warmer' }))
    const box = screen.getByRole('textbox', { name: 'Change what you asked' })
    expect(box).toHaveValue('Make it warmer')                   // the editor opens on the words as they are now
    await userEvent.clear(box)
    await userEvent.type(box, 'Make the first line warmer{Enter}')
    expect(onEdit).toHaveBeenCalledWith(live[0], 'Make the first line warmer')
    await userEvent.click(screen.getByRole('button', { name: 'Remove Make it warmer' }))
    expect(onRemove).toHaveBeenCalledWith(live[0])
  })

  it('keeps the editor open with your words when the server refuses (it already started)', async () => {
    const onEdit = vi.fn().mockRejectedValue(new Error('That one has already started, so it can no longer be edited.'))
    render(<QueuedCard item={goal(1, 'Make it warmer')} live={[goal(1, 'Make it warmer')]} onEdit={onEdit} />)
    await userEvent.click(screen.getByRole('button', { name: 'Edit Make it warmer' }))
    await userEvent.type(screen.getByRole('textbox'), ' now{Enter}')
    expect(screen.getByRole('textbox')).toHaveValue('Make it warmer now')
  })

  it.each([['running', 'Running'], ['done', 'Done'], ['stopped', 'Stopped'], ['failed', 'Failed']] as const)(
    'once %s it shows %s and can no longer be changed', (status, word) => {
      const item = goal(1, 'Make it warmer', status, status === 'failed' ? 'It failed.' : null)
      render(<QueuedCard item={item} live={[item]} onEdit={vi.fn()} onRemove={vi.fn()} />)
      expect(screen.getByTestId('queued-state')).toHaveTextContent(word)
      expect(screen.queryByRole('button')).toBeNull()
    })

  it('another tab or member sees it and changes nothing', () => {
    render(<QueuedCard item={goal(1, 'Make it warmer')} live={[goal(1, 'Make it warmer')]} readOnly onEdit={vi.fn()} onRemove={vi.fn()} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('the thread and Up next read the same cards', () => {
  it('waiting messages stand at the foot of the thread in order; a started one is its turn, wearing its state', () => {
    const thread: ChatMessage[] = [
      { role: 'user', text: 'Make the opening warmer', seq: 1, data: { queued: 1 } },
      { role: 'assistant', text: 'Warmer now.', seq: 2 },
    ]
    const queue = [goal(2, 'Then make the ending shorter'), goal(3, 'And louder')]
    render(<VoltagePane messages={thread} state="working" onSubmit={() => {}} queue={queue} queueRecent={[goal(1, 'Make the opening warmer', 'done')]} />)
    const started = screen.getByTestId('queued-turn')
    expect(within(started).getByTestId('queued-state')).toHaveTextContent('Done')
    expect(started).toHaveTextContent('Make the opening warmer')
    expect(screen.getAllByTestId('queued-card').map((c) => c.getAttribute('aria-label'))).toEqual([
      'Queued 1 of 2: Then make the ending shorter', 'Queued 2 of 2: And louder'])
  })

  it('a running message keeps its card until its words are in the thread, and the question stays last', () => {
    const queue = [goal(4, 'Make it warmer', 'running'), goal(5, 'Make it louder')]
    render(<VoltagePane messages={[]} state="working" onSubmit={() => {}} queue={queue}
      question={{ text: 'Which line?', options: ['Line 1', 'Line 2'] } as never} />)
    expect(screen.getAllByTestId('queued-card').map((c) => c.getAttribute('data-state'))).toEqual(['running', 'queued'])
    const log = screen.getByRole('log')
    const last = log.lastElementChild as HTMLElement
    expect(last.getAttribute('data-testid')).not.toBe('queued-cards')
  })

  it('Up next labels its chips the same way', () => {
    const items = [goal(1, 'Make it warmer', 'running'), goal(2, 'Make it louder'), goal(3, 'And shorter')]
    render(<UpNext items={items} paused={false} onRemove={vi.fn()} onReorder={vi.fn()} onRunNext={vi.fn()} onClear={vi.fn()} />)
    expect(screen.getAllByTestId('up-next-chip').map((c) => c.textContent)).toEqual([
      'Running: Make it warmer', 'Queued 1 of 2: Make it louder', 'Queued 2 of 2: And shorter'])
  })
})
