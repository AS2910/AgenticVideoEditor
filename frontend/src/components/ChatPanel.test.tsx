import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatPanel } from './ChatPanel'

describe('ChatPanel', () => {
  it('disables Preview when canSubmit is false', () => {
    render(<ChatPanel messages={[]} canSubmit={false} onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: /preview/i })).toBeDisabled()
  })

  it('disables Preview when the prompt is empty even if canSubmit', () => {
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: /preview/i })).toBeDisabled()
  })

  it('submits the typed prompt and clears the input', async () => {
    const onSubmit = vi.fn()
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={onSubmit} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, 'change "20% off" to "30% off"')
    await userEvent.click(screen.getByRole('button', { name: /preview/i }))
    expect(onSubmit).toHaveBeenCalledWith('change "20% off" to "30% off"')
    expect(input).toHaveValue('')
  })

  it('submits on Enter', async () => {
    const onSubmit = vi.fn()
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox'), 'make it 40%{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('make it 40%')
  })

  it('renders prior messages', () => {
    render(<ChatPanel messages={['hello there']} canSubmit={true} onSubmit={() => {}} />)
    expect(screen.getByText('hello there')).toBeInTheDocument()
  })

  it('renders children in the message area', () => {
    render(
      <ChatPanel messages={[]} canSubmit={true} onSubmit={() => {}}>
        <div>candidate slot</div>
      </ChatPanel>,
    )
    expect(screen.getByText('candidate slot')).toBeInTheDocument()
  })
})
