import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReadingCard } from './ReadingCard'
import type { Project, Speaker } from '../types'

const PROJECT: Project = {
  project_id: 'p3', filename: 'bhaji.mp4', duration: 48.9,
  media: { kind: 'video', sha256: 's'.repeat(64), duration: 48.9, container: 'mp4' },
  consent: null, transcript: [],
  statements: [
    { text: 'Hi, I want to buy groceries.', start: 5.2, end: 6.9, speaker: 'A' },
    { text: 'Sure, sir.', start: 9.4, end: 9.9, speaker: 'B' },
  ],
}
const SPEAKERS: Speaker[] = [{ label: 'A', name: 'Speaker A', voice_id: null }, { label: 'B', name: 'Shopkeeper', voice_id: null }]
const READING = {
  opening: 'Two people, two lines. The offer is never said.',
  roles: [{ label: 'A', role: 'Customer', why: 'Asks to buy.' }, { label: 'B', role: 'Owner', why: 'Answers.' }],
}
const noop = () => {}

describe("Voltage's first message (UX-7c, from the goal stage)", () => {
  it('says what it read, who speaks by role, and offers things to ask for', async () => {
    const onExample = vi.fn()
    render(<ReadingCard project={PROJECT} reading={READING} speakers={SPEAKERS} onName={noop} onExample={onExample} />)
    expect(screen.getByText(/I've read all 2 lines of/)).toBeInTheDocument()
    expect(screen.getByText(/Two people, two lines\. The offer is never said\./)).toBeInTheDocument()
    // The unnamed speaker shows as Voltage's guess; the named one as named.
    const cast = screen.getByTestId('cast')
    expect(cast).toHaveTextContent('the Customer · my guess')
    expect(cast).toHaveTextContent('Shopkeeper')
    expect(cast).not.toHaveTextContent('Owner')
    await userEvent.click(screen.getByRole('button', { name: 'Add a closing line' }))
    expect(onExample).toHaveBeenCalledWith('Add a closing line')
  })

  it('confirms the guesses in one click, or renames a speaker', async () => {
    const onName = vi.fn()
    const user = userEvent.setup()
    render(<ReadingCard project={PROJECT} reading={READING} speakers={SPEAKERS} onName={onName} onExample={noop} />)
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
    const { rerender } = render(<ReadingCard project={PROJECT} reading={null} speakers={SPEAKERS} onExample={noop} />)
    expect(screen.getByText('Taking it in…')).toBeInTheDocument()
    expect(screen.getByTestId('reading')).toHaveAttribute('aria-busy', 'true')
    rerender(<ReadingCard project={PROJECT} reading={undefined} speakers={SPEAKERS} onExample={noop} />)
    expect(screen.getByText(/Two people speak, 2 lines\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Looks right' })).not.toBeInTheDocument()
  })
})

describe("Voltage's first message on a clip with no speech (UX-5)", () => {
  const silent: Project = { ...PROJECT, statements: [], frames: [{ index: 0, at: 0.3 }] }

  it('says what it saw as short lines, offers a voice-over brief, and its own examples', () => {
    const reading = { opening: 'No one speaks. A beach at dusk.', roles: [], sight: { opening: 'No one speaks. A beach at dusk.', setting: 'A wide beach at dusk', mood: 'calm', people: 'two', text_on_screen: '', place_guess: 'Goa', confidence: 'medium', beats: [] } }
    render(<ReadingCard project={silent} reading={reading} speakers={[]} onPlace={noop} onExample={noop} />)
    expect(screen.getByText(/I've looked at/)).toBeInTheDocument()
    expect(screen.getByText(/No one speaks\. A beach at dusk\./)).toBeInTheDocument()
    expect(within(screen.getByTestId('noticed')).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['A wide beach at dusk'])
    expect(screen.getByRole('button', { name: 'Looks right' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Introduce the place' })).toBeInTheDocument()
  })

  it('lets you confirm the place Voltage guessed, or name the real one', async () => {
    const onPlace = vi.fn()
    const reading = { opening: 'No one speaks.', roles: [], sight: { opening: 'No one speaks.', setting: 'beach', mood: 'calm', people: 'two', text_on_screen: '', place_guess: 'a west-coast Indian beach', confidence: 'medium', beats: [], details: ['tyre tracks in the sand', 'a parasail at the end'] } }
    const { rerender } = render(<ReadingCard project={silent} reading={reading} speakers={[]} onPlace={onPlace} onExample={noop} />)
    expect(within(screen.getByTestId('noticed')).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['tyre tracks in the sand', 'a parasail at the end'])
    await userEvent.click(screen.getByRole('button', { name: 'Looks right' }))
    expect(onPlace).toHaveBeenCalledWith('a west-coast Indian beach')
    await userEvent.click(screen.getByRole('button', { name: 'Somewhere else…' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Where is this?' }), 'Morjim, Goa{Enter}')
    expect(onPlace).toHaveBeenLastCalledWith('Morjim, Goa')
    rerender(<ReadingCard project={silent} reading={{ ...reading, sight: { ...reading.sight, place_confirmed: 'Morjim, Goa' } }} speakers={[]} onPlace={onPlace} onExample={noop} />)
    expect(screen.getByText('Morjim, Goa')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change' })).toBeInTheDocument()
  })
})
