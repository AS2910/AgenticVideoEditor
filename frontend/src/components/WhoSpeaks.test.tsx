import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WhoSpeaks } from './WhoSpeaks'
import type { Statement } from '../types'

const STATEMENTS: Statement[] = [
  { text: 'Hello, are you open?', start: 1.2, end: 3.0, speaker: 'A' },
  { text: 'Feed is live.', start: 7.5, end: 8.4, speaker: 'B' },
  { text: 'Do you have fresh tomatoes today?', start: 9.0, end: 11.0, speaker: 'A' },
]
const SPEAKERS = [{ label: 'A', name: 'Speaker A', voice_id: null }, { label: 'B', name: 'Speaker B', voice_id: null }]

describe('WhoSpeaks (Volt, the first read)', () => {
  it('shows Voltage’s guess for each speaker with their lines and seconds, and names them all on Looks right', async () => {
    const onName = vi.fn()
    render(<WhoSpeaks speakers={SPEAKERS} statements={STATEMENTS} onName={onName}
      reading={{ opening: 'Two people at a stall.', roles: [{ label: 'A', role: 'Customer', why: 'asks for things' }, { label: 'B', role: 'Shopkeeper', why: 'answers' }] }} />)
    const cast = screen.getByTestId('cast')
    expect(cast).toHaveTextContent('the Customer')
    expect(cast).toHaveTextContent('Speaker 1 · 2 lines · 4 s')
    expect(cast).toHaveTextContent('the Shopkeeper')
    expect(cast).toHaveTextContent(/my guess/i)
    await userEvent.click(within(cast).getByRole('button', { name: /looks right/i }))
    expect(onName.mock.calls).toEqual([['A', 'Customer'], ['B', 'Shopkeeper']])
  })

  it('renames one speaker inline, and Escape lets go', async () => {
    const onName = vi.fn()
    render(<WhoSpeaks speakers={SPEAKERS} statements={STATEMENTS} reading={null} onName={onName} />)
    expect(screen.getByTestId('cast')).toHaveTextContent('Speaker 1')
    await userEvent.click(screen.getAllByRole('button', { name: 'Rename' })[0])
    const box = screen.getByRole('textbox', { name: 'Name for speaker A' })
    await userEvent.type(box, 'Riya{Enter}')
    expect(onName).toHaveBeenCalledWith('A', 'Riya')
    await userEvent.click(screen.getAllByRole('button', { name: 'Rename' })[1])
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(onName).toHaveBeenCalledTimes(1)
  })

  it('renders nothing without speakers', () => {
    const { container } = render(<WhoSpeaks speakers={[]} statements={[]} reading={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
