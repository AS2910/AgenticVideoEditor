import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VoltagePane } from './VoltagePane'
import type { ChatMessage } from '../types'
import { unlabelledMoney } from '../lib/money'

const THREAD: ChatMessage[] = [
  { role: 'user', text: 'Make it 30% off', seq: 1 },
  { role: 'assistant', text: 'Read the transcript', kind: 'step', seq: 2, data: { tool: 'read_transcript', t: 1.2 } },
  { role: 'assistant', text: 'Voiced “Get 30% off today only.”', kind: 'step', cost: 0.03, seq: 3, data: { tool: 'synthesize_take', t: 4.8 } },
  { role: 'assistant', text: 'One line, voiced. Hear it on its row.', kind: 'say', seq: 4 },
]

describe('VoltagePane: the thread as turns', () => {
  it('shows your words as a bubble, the steps as a trace with their tools and costs, then what Voltage said', () => {
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} />)
    const log = screen.getByRole('log', { name: 'The conversation' })
    expect(log).toHaveTextContent('Make it 30% off')
    const trace = screen.getByTestId('trace')
    expect(trace).toHaveTextContent('Trace · 2 steps')
    const steps = within(screen.getByRole('list', { name: 'What Voltage did' })).getAllByRole('listitem')
    expect(steps[0]).toHaveTextContent('0:01')
    expect(steps[0]).toHaveTextContent('read_transcript')
    expect(steps[0]).toHaveTextContent('free')
    expect(steps[1]).toHaveTextContent('$0.03')
    expect(log).toHaveTextContent('One line, voiced. Hear it on its row.')
  })

  it('names its state beside the avatar, and the engine on the right', () => {
    render(<VoltagePane messages={[]} state="working" busy engine="Opus 5.5 · high" onSubmit={() => {}} />)
    expect(screen.getByText(/working/)).toBeInTheDocument()
    expect(screen.getByText('Opus 5.5 · high')).toBeInTheDocument()
    expect(screen.getByTestId('wave')).toHaveAttribute('data-state', 'busy')
  })

  it('says what it is doing while a turn runs', () => {
    render(<VoltagePane messages={THREAD.slice(0, 1)} state="working" busy working="Looking at 0:04" onSubmit={() => {}} />)
    expect(screen.getByTestId('turn-working')).toHaveTextContent('Looking at 0:04')
  })
})

describe('VoltagePane: the composer and the gate', () => {
  it('sends the words on Enter and clears the box; the send button says what it will do', async () => {
    const onSubmit = vi.fn()
    render(<VoltagePane messages={[]} state="ready" onSubmit={onSubmit} sendLabel="Answer" cap="Turn cap $0.50" />)
    const box = screen.getByRole('textbox', { name: /describe a change/i })
    await userEvent.type(box, 'Say it warmer{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('Say it warmer')
    expect(box).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Answer' })).toBeInTheDocument()
    expect(screen.getByText('Turn cap $0.50')).toBeInTheDocument()
  })

  it('offers the suggestions as chips that send', async () => {
    const onSubmit = vi.fn()
    render(<VoltagePane messages={[]} state="ready" onSubmit={onSubmit} suggestions={['Add a closing line', 'Fix the brand name']} />)
    await userEvent.click(screen.getByRole('button', { name: 'Fix the brand name' }))
    expect(onSubmit).toHaveBeenCalledWith('Fix the brand name')
  })

  it('shows a gate as a card with the cost and what is left, Go ahead first; an answer is the next turn', async () => {
    const onAnswer = vi.fn()
    render(
      <VoltagePane
        messages={THREAD.slice(0, 1)} state="needs your go" need onSubmit={() => {}} onAnswer={onAnswer}
        question={{ text: 'Re-voice the line in Riya’s voice?', options: ['Go ahead', 'Keep Brian', 'Not yet'], guess: 'Go ahead', gate: true, cost_usd: 0.04, left_usd: 0.31 }}
      />,
    )
    const gate = screen.getByTestId('clarify')
    expect(gate).toHaveTextContent('Re-voice the line in Riya’s voice?')
    expect(gate).toHaveTextContent('$0.04')
    expect(gate).toHaveTextContent('$0.31')
    const buttons = within(gate).getAllByRole('button').map((b) => b.textContent)
    expect(buttons[0]).toBe('Go ahead')
    await userEvent.click(within(gate).getByRole('button', { name: 'Keep Brian' }))
    expect(onAnswer).toHaveBeenCalledWith('Keep Brian')
    expect(screen.getByTestId('wave')).toHaveAttribute('data-state', 'need')
  })

  it('closes a how-to answer with the Help article it used: Show me starts its tour, Read more opens it', async () => {
    const onShowMe = vi.fn()
    render(<VoltagePane messages={[
      { role: 'user', text: 'How do I use the Diwali voice in my next project?', seq: 1 },
      { role: 'assistant', text: 'Looked in Help', kind: 'step', seq: 2, data: { tool: 'search_help', t: 0.8, help: [{ slug: 'saving-and-reusing-your-voices', title: 'Saving and reusing your voices', section: 'Voices', tour: 'save-voice' }] } },
      { role: 'assistant', text: 'Keep it in your voices first.', seq: 3 },
    ]} state="ready" onSubmit={() => {}} onShowMe={onShowMe} />)
    const card = screen.getByTestId('from-help')
    expect(card).toHaveTextContent('From Help · Voices')
    expect(within(card).getByRole('link', { name: 'Read more' })).toHaveAttribute('href', '#help/saving-and-reusing-your-voices')
    await userEvent.click(within(card).getByRole('button', { name: '⚡ Show me' }))
    expect(onShowMe).toHaveBeenCalledWith('save-voice')
  })
})

describe('VoltagePane: spend scopes in the trace', () => {
  const SPEND = {
    turn: { spent_usd: 0.03, ceiling_usd: 0.5, label: 'This turn' },
    video: { spent_usd: 0.61, ceiling_usd: 2, label: 'This video' },
    project: { spent_usd: 0.61, ceiling_usd: 10, label: 'Project Ashish Testing' },
    month: { spent_usd: 3.1, ceiling_usd: 100, label: 'October' },
    binding: 'video' as const,
  }

  it('closes the latest trace with the turn, the video and the project, each named', () => {
    render(<VoltagePane messages={THREAD} state="ready" cap="Turn cap $0.50" spend={SPEND} onSubmit={() => {}} />)
    expect(screen.getByTestId('trace-spend')).toHaveTextContent('This turn $0.03 · video $0.61 · project $0.61')
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('leaves the project out for a standalone video', () => {
    const { project: _p, ...alone } = SPEND
    render(<VoltagePane messages={THREAD} state="ready" spend={{ ...alone, binding: 'video' }} onSubmit={() => {}} />)
    expect(screen.getByTestId('trace-spend')).toHaveTextContent(/^This turn \$0\.03 · video \$0\.61$/)
  })

  it('labels every figure in a gate card and a folded turn', () => {
    const thread: ChatMessage[] = [...THREAD, { role: 'user', text: 'And the second line', seq: 5 },
      { role: 'assistant', text: 'Thinking', kind: 'step', cost: 0.02, seq: 6, data: { tool: 'thinking', t: 2 } }]
    render(<VoltagePane messages={thread} state="needs your go" need cap="Turn cap $0.50" onSubmit={() => {}}
      question={{ text: 'Voice it for about $0.04?', options: ['Go', 'Not yet'], gate: true, cost_usd: 0.04, left_usd: 0.46 } as never} />)
    expect(screen.getByTestId('earlier-turn')).toHaveTextContent('$0.03')
    expect(unlabelledMoney(screen.getByRole('log'))).toEqual([])
  })
})
