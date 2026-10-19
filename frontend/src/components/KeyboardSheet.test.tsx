import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyboardSheet } from './KeyboardSheet'

describe('KeyboardSheet', () => {
  it('lists every key in two columns, as a dialog with focus on its title', async () => {
    render(<KeyboardSheet open onClose={() => {}} />)
    const sheet = screen.getByRole('dialog', { name: 'Keyboard' })
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Keyboard' })).toHaveFocus())
    expect(sheet).toHaveTextContent('Move and listen')
    expect(sheet).toHaveTextContent('Change')
    expect(within(sheet).getAllByRole('definition')).toHaveLength(11)
    for (const k of ['↑', '↓', 'Space', 'Enter', 'Esc', 'K', 'U', 'A', 'Delete', 'S', '/', '?']) expect(within(sheet).getAllByText(k).length).toBeGreaterThan(0)
    expect(sheet).toHaveTextContent('Add the proposal to the video')
    expect(sheet).toHaveTextContent('Shortcuts never spend money on their own')
    expect(within(sheet).getByRole('link', { name: 'All of Help →' })).toHaveAttribute('href', '#help')
  })

  it('closes on Esc and on the Close button, giving focus back', async () => {
    const onClose = vi.fn()
    render(<><button type="button">opener</button><KeyboardSheet open onClose={onClose} /></>)
    await screen.findByRole('dialog')
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Esc · Close' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('renders nothing while closed', () => {
    render(<KeyboardSheet open={false} onClose={() => {}} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
