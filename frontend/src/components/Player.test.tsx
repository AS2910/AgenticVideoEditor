import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { Player } from './Player'
import { rulerMarks } from '../timeline/ruler'

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

describe('Player transport (redesign)', () => {
  it('shows a timecode of position and length', () => {
    render(<Player src="/a.mp4" duration={48.9} currentTime={7.54} onSeek={() => {}} />)
    expect(screen.getByTestId('timecode')).toHaveTextContent('0:07.5 / 0:48.9')
  })

  it('carries extra controls in the transport row', () => {
    render(
      <Player src="/a.mp4" duration={8} currentTime={0} onSeek={() => {}}>
        <button>Edited</button>
      </Player>,
    )
    expect(screen.getByRole('button', { name: 'Edited' })).toBeInTheDocument()
  })
})

describe('Player as the monitor (UX-7b)', () => {
  it('captions the picture with the line at the playhead', () => {
    render(<Player src="/a.mp4" duration={8} currentTime={1} onSeek={() => {}} caption={<>Get <ins>30%</ins> off</>} />)
    expect(screen.getByTestId('caption')).toHaveTextContent('Get 30% off')
    expect(screen.getByTestId('caption').querySelector('ins')).toHaveTextContent('30%')
  })

  it('marks the scrubber with proposals, lines in the video and steps waiting on you (Volt)', () => {
    render(
      <Player
        src="/a.mp4" duration={10} currentTime={2.5} onSeek={() => {}}
        markers={[{ at: 1, tone: 'ink', label: 'In the video: Thirty off.' }, { at: 4, tone: 'volt', label: 'Proposed: Bhaji Cam' }, { at: 8, tone: 'warn', label: 'Waiting on you' }]}
      />,
    )
    const marks = screen.getAllByTestId('marker')
    expect(marks.map((m) => m.getAttribute('data-tone'))).toEqual(['ink', 'volt', 'warn'])
    expect(marks[1].style.left).toBe('40%')
    expect(marks[1]).toHaveAttribute('title', 'Proposed: Bhaji Cam')
    expect(screen.getByTestId('head').style.left).toBe('25%')
  })

  it('tags the picture with what plays, and sweeps it while Voltage looks (Volt)', () => {
    render(<Player src="/a.mp4" duration={10} currentTime={0} onSeek={() => {}} badge="With proposals" scanning="Voltage is looking at 0:04" />)
    expect(screen.getByTestId('mode-badge')).toHaveTextContent('With proposals')
    expect(screen.getByRole('status')).toHaveTextContent('Voltage is looking at 0:04')
    expect(screen.getByTestId('scan')).toBeInTheDocument()
  })

  it('rules the timeline with a label every few seconds and the end', () => {
    expect(rulerMarks(16.2).map((m) => m.label)).toEqual(['0:00', '0:05', '0:10', '0:15', '0:16'])
    expect(rulerMarks(7.5).map((m) => m.label)).toEqual(['0:00', '0:02', '0:04', '0:06', '0:07.5'])
    expect(rulerMarks(48.9).map((m) => m.label)).toEqual(['0:00', '0:10', '0:20', '0:30', '0:40', '0:49'])
    expect(rulerMarks(52.42).map((m) => m.label)).toEqual(['0:00', '0:10', '0:20', '0:30', '0:40', '0:52'])
    expect(rulerMarks(0)).toEqual([])
  })
})
