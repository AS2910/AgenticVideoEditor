/**
 * A voice for a silent clip (UX-5, SV-4): the transcript with no lines is the
 * place editor; a span is typed, nudged or dragged, never drag-only; Hear it
 * sends the span and the words as a line over the picture.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LineDoc } from './LineDoc'
import { PlaceEditor } from './PlaceEditor'

const handlers = () => ({
  onSeek: vi.fn(), onHear: vi.fn(), onKeep: vi.fn(), onAnother: vi.fn(), onAnswer: vi.fn(), onUndo: vi.fn(),
  onRemove: vi.fn(), onPlayTake: vi.fn(), onDismiss: vi.fn(),
})

describe('placing a voice-over', () => {
  it('is the transcript when a clip has no speech, and hears a line over the chosen span', async () => {
    const h = handlers()
    render(<LineDoc statements={[]} currentTime={0} duration={7.5} {...h} />)
    expect(screen.getByRole('heading', { name: 'Voice-over' })).toBeInTheDocument()
    const editor = screen.getByTestId('place-editor')
    expect(within(editor).getByRole('heading', { name: 'Where should the voice-over go?' })).toBeInTheDocument()
    expect(within(editor).getByRole('textbox', { name: 'Starts at' })).toHaveValue('0:00.50')
    expect(within(editor).getByRole('textbox', { name: 'Ends at' })).toHaveValue('0:03.50')
    expect(within(editor).getByRole('button', { name: 'Hear it' })).toBeDisabled()
    await userEvent.type(within(editor).getByRole('textbox', { name: 'Words for the voice-over' }), 'Welcome to Goa')
    await userEvent.click(within(editor).getByRole('button', { name: 'Warmer' }))
    await userEvent.click(within(editor).getByRole('button', { name: 'Hear it' }))
    expect(h.onHear).toHaveBeenCalledWith('0.500-3.500', expect.objectContaining({
      selection: { start: 0.5, end: 3.5 }, text: 'Welcome to Goa', mix: 'layer', delivery: 'warmer',
    }))
  })

  it('nudges the span from the keyboard and refuses a span that leaves the clip', async () => {
    const onHear = vi.fn()
    render(<PlaceEditor duration={7.5} onHear={onHear} />)
    await userEvent.click(screen.getByRole('button', { name: 'Start later' }))
    expect(screen.getByRole('textbox', { name: 'Starts at' })).toHaveValue('0:00.60')
    expect(screen.getByRole('textbox', { name: 'Ends at' })).toHaveValue('0:03.60')
    const end = screen.getByRole('textbox', { name: 'Ends at' })
    await userEvent.clear(end)
    await userEvent.type(end, '0:09.00')
    expect(end).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent("inside the clip's 0:07.50")
    await userEvent.type(screen.getByRole('textbox', { name: 'Words for the voice-over' }), 'Hello')
    expect(screen.getByRole('button', { name: 'Hear it' })).toBeDisabled()
  })

  it('puts a block on the monitor bar for the span, and follows the block when it is dragged', () => {
    const onPlacing = vi.fn()
    const { rerender } = render(<PlaceEditor duration={7.5} onHear={() => {}} onPlacing={onPlacing} placing={null} />)
    expect(onPlacing).toHaveBeenCalledWith({ id: 'voice-over', start: 0.5, duration: 3 })
    rerender(<PlaceEditor duration={7.5} onHear={() => {}} onPlacing={onPlacing} placing={{ id: 'voice-over', start: 2, duration: 3 }} />)
    expect(screen.getByRole('textbox', { name: 'Starts at' })).toHaveValue('0:02.00')
    expect(screen.getByRole('textbox', { name: 'Ends at' })).toHaveValue('0:05.00')
  })

  it('shows a placed voice-over as its own row, and offers another', () => {
    const h = handlers()
    render(<LineDoc statements={[{ text: '', start: 0.5, end: 3.5, speaker: null, placed: true }]} currentTime={0} duration={7.5} {...h}
      lines={{ '0.500-3.500': { status: 'working', takes: [] } }} />)
    expect(screen.getByRole('listitem', { name: 'Line at 0:00' })).toHaveTextContent('Voice-over, 0:00.50–0:03.50')
    expect(screen.getAllByRole('status').some((el) => el.textContent?.includes('Voicing…'))).toBe(true)
    expect(screen.getByRole('button', { name: /add another voice-over/i })).toBeInTheDocument()
  })
})
