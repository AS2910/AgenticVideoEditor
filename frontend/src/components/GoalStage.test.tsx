import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GoalStage } from './GoalStage'
import type { Project } from '../types'

const PROJECT: Project = {
  project_id: 'p3', filename: 'bhaji.mp4', duration: 48.9,
  media: { kind: 'video', sha256: 's'.repeat(64), duration: 48.9, container: 'mp4' },
  consent: null, transcript: [],
  statements: [
    { text: 'Hi, I want to buy groceries.', start: 5.2, end: 6.9, speaker: 'A' },
    { text: 'Sure, sir.', start: 9.4, end: 9.9, speaker: 'B' },
  ],
  speakers: [{ label: 'A', name: 'Speaker A', voice_id: null }, { label: 'B', name: 'Shopkeeper', voice_id: null }],
}
const READING = {
  opening: 'Two people, two lines. The offer is never said.',
  roles: [{ label: 'A', role: 'Customer', why: 'Asks to buy.' }, { label: 'B', role: 'Owner', why: 'Answers.' }],
}
const noop = () => {}

describe('GoalStage (UX-2)', () => {
  it('shows the clip: its lines by time, who says them by role, and a specific opening', () => {
    render(<GoalStage project={PROJECT} reading={READING} onPlan={noop} onHandsOn={noop} onName={noop} />)
    expect(screen.getByText(/Two people, two lines\. The offer is never said\./)).toBeInTheDocument()
    const lines = within(screen.getByRole('list'))
    expect(lines.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      '0:05CustomerHi, I want to buy groceries.', '0:09ShopkeeperSure, sir.',
    ])
    // The unnamed speaker shows as Voltage's guess; the named one as named.
    const cast = screen.getByTestId('cast')
    expect(cast).toHaveTextContent('the Customer · my guess')
    expect(cast).toHaveTextContent('Shopkeeper')
    expect(cast).not.toHaveTextContent('Owner')
  })

  it('confirms the guesses in one click, or renames a speaker', async () => {
    const onName = vi.fn()
    const user = userEvent.setup()
    render(<GoalStage project={PROJECT} reading={READING} onPlan={noop} onHandsOn={noop} onName={onName} />)
    await user.click(screen.getByRole('button', { name: 'Looks right' }))
    expect(onName).toHaveBeenCalledTimes(1)
    expect(onName).toHaveBeenCalledWith('A', 'Customer')
    await user.click(screen.getAllByRole('button', { name: 'Rename' })[1])
    const box = screen.getByRole('textbox', { name: 'Name for speaker B' })
    expect(box).toHaveValue('Shopkeeper')
    await user.clear(box)
    await user.type(box, 'Ravi{Enter}')
    expect(onName).toHaveBeenLastCalledWith('B', 'Ravi')
  })

  it('says it is taking the clip in while the reading is on its way, and falls back to the count', () => {
    const { rerender } = render(<GoalStage project={PROJECT} reading={null} onPlan={noop} onHandsOn={noop} />)
    expect(screen.getByText('Taking it in…')).toBeInTheDocument()
    rerender(<GoalStage project={PROJECT} reading={undefined} onPlan={noop} onHandsOn={noop} />)
    expect(screen.getByText(/Two people speak, 2 lines\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Looks right' })).not.toBeInTheDocument()
  })

  it('plans the goal on Enter', async () => {
    const onPlan = vi.fn()
    render(<GoalStage project={PROJECT} reading={READING} onPlan={onPlan} onHandsOn={noop} />)
    await userEvent.type(screen.getByRole('textbox', { name: /what the video should say/i }), 'make it 30% off{Enter}')
    expect(onPlan).toHaveBeenCalledWith('make it 30% off')
  })
})

describe('GoalStage on a clip with no speech (UX-5)', () => {
  it('shows the frames where the lines would be, a voice-over brief, and its own examples', () => {
    const silent: Project = { ...PROJECT, statements: [], speakers: [], frames: [{ index: 0, at: 0.3 }, { index: 1, at: 3.9 }, { index: 2, at: 7.2 }] }
    const reading = { opening: 'No one speaks. A beach at dusk.', roles: [], sight: { opening: 'No one speaks. A beach at dusk.', setting: 'A wide beach at dusk', mood: 'calm', people: 'two', text_on_screen: '', place_guess: 'Goa', confidence: 'medium', beats: [] } }
    render(<GoalStage project={silent} reading={reading} onPlan={noop} onHandsOn={noop} onName={noop} onPlace={noop} />)
    expect(screen.getByText(/I've looked at/)).toBeInTheDocument()
    expect(screen.getByText(/No one speaks\. A beach at dusk\./)).toBeInTheDocument()
    const frames = within(screen.getByTestId('frames')).getAllByRole('button')
    expect(frames).toHaveLength(3)
    expect(frames[1]).toHaveAttribute('aria-label', 'Jump to 0:03')
    expect(within(frames[1]).getByRole('presentation', { hidden: true })).toHaveAttribute('src', '/api/projects/p3/frames/1')
    // The clip itself is there to play, and what Voltage noticed is short lines plus one decision.
    expect(screen.getByLabelText('bhaji.mp4, 48.9 seconds')).toHaveAttribute('src', `/api/projects/p3/artifacts/${'s'.repeat(64)}`)
    expect(within(screen.getByTestId('noticed')).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['A wide beach at dusk'])
    expect(screen.getByRole('button', { name: 'Looks right' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Introduce the place' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Place a voice-over yourself instead' })).toBeInTheDocument()
  })

  it('clicking a frame jumps the clip there, and offers to say it from that moment', async () => {
    const silent: Project = { ...PROJECT, statements: [], speakers: [], frames: [{ index: 0, at: 3.9 }] }
    render(<GoalStage project={silent} reading={null} onPlan={noop} onHandsOn={noop} />)
    await userEvent.click(screen.getByRole('button', { name: 'Jump to 0:03' }))
    expect((screen.getByLabelText('bhaji.mp4, 48.9 seconds') as HTMLVideoElement).currentTime).toBe(3.9)
    await userEvent.click(screen.getByRole('button', { name: 'Say it from 0:03' }))
    expect(screen.getByRole('textbox', { name: 'What the video should say' })).toHaveValue('Say it from 0:03: ')
  })

  it('lets you confirm the place Voltage guessed, or name the real one', async () => {
    const onPlace = vi.fn()
    const silent: Project = { ...PROJECT, statements: [], speakers: [], frames: [] }
    const reading = { opening: 'No one speaks.', roles: [], sight: { opening: 'No one speaks.', setting: 'beach', mood: 'calm', people: 'two', text_on_screen: '', place_guess: 'a west-coast Indian beach', confidence: 'medium', beats: [], details: ['tyre tracks in the sand', 'a parasail at the end'] } }
    const { rerender } = render(<GoalStage project={silent} reading={reading} onPlan={noop} onHandsOn={noop} onPlace={onPlace} />)
    expect(within(screen.getByTestId('noticed')).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['tyre tracks in the sand', 'a parasail at the end'])
    await userEvent.click(screen.getByRole('button', { name: 'Looks right' }))
    expect(onPlace).toHaveBeenCalledWith('a west-coast Indian beach')
    await userEvent.click(screen.getByRole('button', { name: 'Somewhere else…' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Where is this?' }), 'Morjim, Goa{Enter}')
    expect(onPlace).toHaveBeenLastCalledWith('Morjim, Goa')
    rerender(<GoalStage project={silent} reading={{ ...reading, sight: { ...reading.sight, place_confirmed: 'Morjim, Goa' } }} onPlan={noop} onHandsOn={noop} onPlace={onPlace} />)
    expect(screen.getByText('Morjim, Goa')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change' })).toBeInTheDocument()
  })
})
