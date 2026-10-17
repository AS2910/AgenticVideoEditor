import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatPanel } from './ChatPanel'

describe('ChatPanel', () => {
  it('disables Preview when canSubmit is false', () => {
    render(<ChatPanel messages={[]} canSubmit={false} onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  })

  it('disables Preview when the prompt is empty even if canSubmit', () => {
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  })

  it('submits the typed prompt and clears the input', async () => {
    const onSubmit = vi.fn()
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={onSubmit} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, 'change "20% off" to "30% off"')
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    expect(onSubmit).toHaveBeenCalledWith('change "20% off" to "30% off"')
    expect(input).toHaveValue('')
  })

  it('submits on Enter', async () => {
    const onSubmit = vi.fn()
    render(<ChatPanel messages={[]} canSubmit={true} onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox'), 'make it 40%{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('make it 40%')
  })

  it('renders both sides of the conversation', () => {
    render(
      <ChatPanel
        messages={[
          { role: 'user', text: 'make the background white' },
          { role: 'assistant', text: 'This editor only changes spoken dialogue.' },
        ]}
        canSubmit={true}
        onSubmit={() => {}}
      />,
    )
    expect(screen.getByText('make the background white')).toBeInTheDocument()
    expect(screen.getByText('This editor only changes spoken dialogue.')).toBeInTheDocument()
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

it('folds what Voltage did into one small list with the money on the right (Phase 20)', () => {
  render(
    <ChatPanel
      messages={[
        { role: 'user', text: 'Describe the place in an Indian voice' },
        { role: 'assistant', text: 'Looked at 6 frames', kind: 'step', seq: 2 },
        { role: 'assistant', text: 'Voiced “Welcome to Goa.” with Varsha — warm', kind: 'step', cost: 0.03, seq: 3 },
        { role: 'assistant', text: 'Voiced it again, slower', kind: 'step', cost: 0.04, seq: 4 },
        { role: 'assistant', text: 'One line over the opening shot. Hear it below.' },
      ]}
      canSubmit
      onSubmit={() => {}}
    />,
  )
  const list = screen.getByRole('list', { name: 'What Voltage did' })
  const items = within(list).getAllByRole('listitem')
  expect(items.map((li) => li.textContent)).toEqual([
    '·Looked at 6 frames',
    '·Voiced “Welcome to Goa.” with Varsha — warm$0.03',
    '·Voiced it again, slower$0.04',
    '$0.07 this turn',
  ])
  expect(screen.getByText('One line over the opening shot. Hear it below.')).toBeInTheDocument()
})
