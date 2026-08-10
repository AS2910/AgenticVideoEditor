import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Timeline } from './Timeline'
import type { Word } from '../types'

const WORDS: Word[] = [
  { text: 'Get', start: 0.0, end: 0.4 },
  { text: '20%', start: 0.4, end: 0.9 },
  { text: 'off', start: 0.9, end: 1.3 },
]

describe('Timeline', () => {
  it('selects a word span when a word is clicked', async () => {
    const onSelect = vi.fn()
    render(
      <Timeline words={WORDS} duration={2.3} selection={null} currentTime={0} onSelect={onSelect} />,
    )
    await userEvent.click(screen.getByText('20%'))
    expect(onSelect).toHaveBeenCalledWith({ start: 0.4, end: 0.9 })
  })

  it('renders a selection region when a selection is present', () => {
    render(
      <Timeline
        words={WORDS}
        duration={2.3}
        selection={{ start: 0.4, end: 1.3 }}
        currentTime={0}
        onSelect={() => {}}
      />,
    )
    expect(screen.getByTestId('selection-region')).toBeInTheDocument()
  })

  it('does not render a selection region when there is no selection', () => {
    render(
      <Timeline words={WORDS} duration={2.3} selection={null} currentTime={0} onSelect={() => {}} />,
    )
    expect(screen.queryByTestId('selection-region')).not.toBeInTheDocument()
  })

  it('positions the selection region and playhead by time', () => {
    render(
      <Timeline
        words={WORDS}
        duration={2.3}
        selection={{ start: 0.4, end: 1.3 }}
        currentTime={1.15}
        onSelect={() => {}}
      />,
    )
    // 0.4 / 2.3 ≈ 17.39%, span 0.9 / 2.3 ≈ 39.13%
    const region = screen.getByTestId('selection-region')
    expect(region.style.left).toMatch(/^17\.39/)
    expect(region.style.width).toMatch(/^39\.13/)
    // playhead at the midpoint
    expect(screen.getByTestId('playhead').style.left).toBe('50%')
  })
})
