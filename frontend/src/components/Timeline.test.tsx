import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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

  it('extends the selection to a shift-clicked word', async () => {
    const onSelect = vi.fn()
    render(
      <Timeline
        words={WORDS}
        duration={2.3}
        selection={{ start: 0.4, end: 0.9 }}
        currentTime={0}
        onSelect={onSelect}
      />,
    )
    const user = userEvent.setup()
    await user.keyboard('{Shift>}')
    await user.click(screen.getByText('off'))
    expect(onSelect).toHaveBeenLastCalledWith({ start: 0.4, end: 1.3 })
  })

  it('selects the words a drag passes over, snapped to word edges', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <Timeline words={WORDS} duration={2.3} selection={null} currentTime={0} onSelect={onSelect} />,
    )
    const track = container.querySelector('[class*="track"]') as HTMLElement
    // 230px wide track from x=0, so 1px = 0.01 s
    track.getBoundingClientRect = () =>
      ({ left: 0, width: 230, top: 0, height: 56, right: 230, bottom: 56 }) as DOMRect
    fireEvent.pointerDown(track, { button: 0, clientX: 50 }) // 0.5 s, inside '20%'
    fireEvent.pointerMove(window, { clientX: 100 }) // 1.0 s, inside 'off'
    fireEvent.pointerUp(window, { clientX: 100 })
    expect(onSelect).toHaveBeenLastCalledWith({ start: 0.4, end: 1.3 })
  })

  it('treats a press without movement as a click, not a drag', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <Timeline words={WORDS} duration={2.3} selection={null} currentTime={0} onSelect={onSelect} />,
    )
    const track = container.querySelector('[class*="track"]') as HTMLElement
    fireEvent.pointerDown(track, { button: 0, clientX: 50 })
    fireEvent.pointerMove(window, { clientX: 51 })
    fireEvent.pointerUp(window, { clientX: 51 })
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('says so when the video has no speech', () => {
    render(<Timeline words={[]} duration={8} selection={null} currentTime={0} onSelect={() => {}} />)
    expect(screen.getByText(/No speech found/)).toBeInTheDocument()
  })
})

describe('Timeline zoom (Phase 10)', () => {
  const LONG: Word[] = Array.from({ length: 80 }, (_, i) => ({ text: `w${i}`, start: i * 0.6, end: i * 0.6 + 0.4 }))

  it('opens a long clip zoomed so words are readable, and can fit it back', async () => {
    const { container } = render(
      <Timeline words={LONG} duration={48.9} selection={null} currentTime={0} onSelect={() => {}} />,
    )
    const track = () => container.querySelector('[class*="track"]') as HTMLElement
    expect(track().style.width).toBe(`${48.9 * 110}px`)
    await userEvent.click(screen.getByRole('button', { name: 'Fit' }))
    expect(track().style.width).toBe('')
  })

  it('fits a short clip from the start', () => {
    const { container } = render(
      <Timeline words={WORDS} duration={2.3} selection={null} currentTime={0} onSelect={() => {}} />,
    )
    expect((container.querySelector('[class*="track"]') as HTMLElement).style.width).toBe('')
    expect(screen.getByRole('button', { name: 'Fit' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('zooms in from the current zoom', async () => {
    const { container } = render(
      <Timeline words={LONG} duration={48.9} selection={null} currentTime={0} onSelect={() => {}} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect((container.querySelector('[class*="track"]') as HTMLElement).style.width)
      .toBe(`${48.9 * 165}px`)
  })
})
