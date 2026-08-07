import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { Player } from './Player'

describe('Player', () => {
  it('renders a scrubber bound to duration and reports seeks', () => {
    const onSeek = vi.fn()
    render(<Player src="/sample-ad.mp4" duration={2.3} currentTime={0} onSeek={onSeek} />)
    const scrubber = screen.getByRole('slider')
    expect(scrubber).toHaveAttribute('max', '2.3')
    fireEvent.change(scrubber, { target: { value: '1.1' } })
    expect(onSeek).toHaveBeenCalledWith(1.1)
  })

  it('has a play/pause control', () => {
    render(<Player src="/sample-ad.mp4" duration={2.3} currentTime={0} onSeek={() => {}} />)
    expect(screen.getByRole('button', { name: /play|pause/i })).toBeInTheDocument()
  })
})
