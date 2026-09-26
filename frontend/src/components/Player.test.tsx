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

describe('Player playback (Phase 8 fix)', () => {
  it('plays with sound', () => {
    const { container } = render(<Player src="/a.mp4" duration={8} currentTime={0} onSeek={() => {}} />)
    expect((container.querySelector('video') as HTMLVideoElement).muted).toBe(false)
  })

  it('moves the video when the slider is dragged', () => {
    const onSeek = vi.fn()
    const { container } = render(<Player src="/a.mp4" duration={8} currentTime={0} onSeek={onSeek} />)
    fireEvent.change(screen.getByRole('slider', { name: /seek/i }), { target: { value: '3.5' } })
    expect((container.querySelector('video') as HTMLVideoElement).currentTime).toBe(3.5)
    expect(onSeek).toHaveBeenCalledWith(3.5)
  })

  it('reports the time as the video plays', () => {
    const onTimeUpdate = vi.fn()
    const { container } = render(
      <Player src="/a.mp4" duration={8} currentTime={0} onSeek={() => {}} onTimeUpdate={onTimeUpdate} />,
    )
    const video = container.querySelector('video') as HTMLVideoElement
    video.currentTime = 2.25
    fireEvent.timeUpdate(video)
    expect(onTimeUpdate).toHaveBeenCalledWith(2.25)
  })
})
