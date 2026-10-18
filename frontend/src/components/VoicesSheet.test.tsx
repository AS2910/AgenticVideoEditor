import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VoicesSheet } from './VoicesSheet'

describe('VoicesSheet (20i): your voices, uploaded under a name', () => {
  it('lists the voices you have, with Remove, and says so when there are none', async () => {
    const onDelete = vi.fn(async () => {})
    const { rerender } = render(<VoicesSheet open voices={[]} onUpload={vi.fn()} onDelete={onDelete} onClose={vi.fn()} />)
    expect(screen.getByText('No voice of yours yet.')).toBeInTheDocument()
    rerender(<VoicesSheet open voices={[{ voice_id: 'v1', name: 'Ashish', seconds: 14.2, at: '2026-10-18T00:00:00Z' }]} onUpload={vi.fn()} onDelete={onDelete} onClose={vi.fn()} />)
    const list = within(screen.getByRole('region', { name: 'The voices you have' }))
    expect(list.getByText('Ashish')).toBeInTheDocument()
    expect(list.getByText('14 s of you')).toBeInTheDocument()
    await userEvent.click(list.getByRole('button', { name: 'Remove Ashish' }))
    expect(onDelete).toHaveBeenCalledWith('v1')
  })

  it('uploads only with a name, a file and your word, then clears the form', async () => {
    const onUpload = vi.fn(async () => {})
    render(<VoicesSheet open voices={[]} onUpload={onUpload} onDelete={vi.fn()} onClose={vi.fn()} />)
    const keep = screen.getByRole('button', { name: 'Keep this voice' })
    expect(keep).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Name it'), 'Ashish')
    const file = new File(['bytes'], 'me.wav', { type: 'audio/wav' })
    await userEvent.upload(screen.getByLabelText('A recording of you'), file)
    expect(keep).toBeDisabled()   // not without your word
    await userEvent.click(screen.getByRole('checkbox'))
    expect(keep).toBeEnabled()
    await userEvent.click(keep)
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith('Ashish', file))
    expect(screen.getByLabelText('Name it')).toHaveValue('')
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('shows the server\'s reason when a voice cannot be made', async () => {
    const onUpload = vi.fn(async () => { throw new Error('That is 3 s; at least 10 s of your voice is needed to clone it.') })
    render(<VoicesSheet open voices={[]} onUpload={onUpload} onDelete={vi.fn()} onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Name it'), 'Me')
    await userEvent.upload(screen.getByLabelText('A recording of you'), new File(['x'], 'short.wav', { type: 'audio/wav' }))
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Keep this voice' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 10 s of your voice')
  })
})
