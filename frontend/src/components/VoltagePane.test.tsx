import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
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

  it('offers chips from the video: a click puts the prompt in the box, editable, and Enter sends it (2026-10-20)', async () => {
    const onSubmit = vi.fn()
    const onChipEvent = vi.fn()
    const chips = [
      { label: 'Say Bhaji Cam clearly', prompt: 'Voice line 2 again so “Bhaji Cam” is said clearly.', kind: 'fix' as const, grounded_in: 'words' as const },
      { label: 'Add the 30% Diwali offer', prompt: 'Add the 30% Diwali offer at the end.', kind: 'change' as const, grounded_in: 'brief' as const },
      { label: 'Try a warmer voice', prompt: 'Try a warmer voice for line 1.', kind: 'voice' as const, grounded_in: 'words' as const },
      { label: 'Export', prompt: 'Export the video.', kind: 'finish' as const, grounded_in: 'time' as const },
      { label: 'Fifth', prompt: 'A fifth chip.', kind: 'add' as const, grounded_in: 'time' as const },
    ]
    render(<VoltagePane messages={[]} state="ready" onSubmit={onSubmit} suggestions={chips} onChipEvent={onChipEvent} />)
    const group = screen.getByRole('group', { name: 'Suggestions for this video' })
    expect(within(group).getAllByRole('button')).toHaveLength(4)
    expect(onChipEvent).toHaveBeenCalledWith('shown', chips[0])
    await userEvent.click(within(group).getByRole('button', { name: 'Say Bhaji Cam clearly' }))
    const box = screen.getByRole('textbox', { name: 'Describe a change' }) as HTMLTextAreaElement
    expect(box).toHaveValue(chips[0].prompt)
    expect(onSubmit).not.toHaveBeenCalled()                       // no spend from a single click
    expect(onChipEvent).toHaveBeenLastCalledWith('clicked', chips[0])
    await userEvent.type(box, ' Slowly.{Enter}')
    expect(onSubmit).toHaveBeenCalledWith(`${chips[0].prompt} Slowly.`)
    expect(onChipEvent).toHaveBeenLastCalledWith('sent', chips[0], true)
  })

  it('shows a question settled in the editor as quiet: its options off, and why (2026-10-20)', () => {
    const onAnswer = vi.fn()
    render(<VoltagePane messages={[]} state="ready" onSubmit={() => {}} onAnswer={onAnswer}
      question={{ text: 'How should I handle the middle line?', options: ['Voice it next turn', 'Add four now', 'Let me listen first'], guess: 'Voice it next turn',
        resolved: { why: 'you added all four lines', by: 'editor', at: '2026-10-20T10:00:00Z' } }} />)
    const card = screen.getByTestId('clarify')
    expect(card).toHaveAttribute('data-resolved', 'true')
    expect(within(card).getByTestId('clarify-status')).toHaveTextContent('Answered in the editor: you added all four lines.')
    expect(within(card).getAllByRole('button').every((b) => (b as HTMLButtonElement).disabled)).toBe(true)
    expect(within(card).queryByTestId('pick-tag')).toBeNull()
  })

  it('turns "line 3" in Voltage\'s words into a link that asks the transcript for the row', async () => {
    const heard = vi.fn()
    window.addEventListener('voltage:goto-line', (e) => heard((e as CustomEvent).detail))
    render(<VoltagePane messages={[{ role: 'user', text: 'Tighten it', kind: 'say', seq: 1 }, { role: 'assistant', text: 'Line 3 runs long; **line 4** is fine.', kind: 'say', seq: 2 }]} state="ready" onSubmit={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Line 3' }))
    expect(heard).toHaveBeenCalledWith({ line: 3 })
  })

  it('hides the chips while a turn runs', () => {
    render(<VoltagePane messages={[]} state="working" working="Voicing line 2" onSubmit={() => {}}
      suggestions={[{ label: 'Export', prompt: 'Export the video.', kind: 'finish', grounded_in: 'time' }]} />)
    expect(screen.queryByRole('group', { name: 'Suggestions for this video' })).not.toBeInTheDocument()
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

describe('VoltagePane: rendering at any width (pane-render)', () => {
  const LONG = 'Voice the shorter middle line next turn, then add all five lines together so the commentary builds to the knockdown'
  const ASKED = {
    text: 'The middle line is over this turn’s cap. What should I do?',
    options: ['Add the four now', 'Voice it next turn', LONG],
    details: ['Add the four finished lines now and leave 7 to 10 s quiet.', null, null],
    guess: 'Voice it next turn', gate: false, left_usd: 0, cap_usd: 0.5,
  }

  it('puts Voltage’s pick first with its tag, and drops the separate “My guess is” sentence', () => {
    render(<VoltagePane messages={THREAD} state="needs your go" need onSubmit={() => {}} question={ASKED} />)
    const card = screen.getByTestId('clarify')
    const buttons = within(card).getAllByRole('button')
    expect(buttons[0]).toHaveTextContent('Voice it next turn')
    expect(within(buttons[0]).getByTestId('pick-tag')).toHaveTextContent('Voltage\'s pick')
    expect(within(card).getAllByTestId('pick-tag')).toHaveLength(1)
    expect(card).not.toHaveTextContent(/my guess is/i)
    expect(card).toHaveTextContent('Pick one, or answer in your own words.')
  })

  it('wraps every option: stacked, text-left, fit to its words, never wider than the card', () => {
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} question={ASKED} />)
    const stack = screen.getByTestId('clarify-options')
    expect(stack).toHaveClass('flex-col', 'gap-2', 'w-full')
    for (const b of within(stack).getAllByRole('button')) expect(b).toHaveClass('opt')
  })

  it('gives a long option a short label with the full sentence beneath; a given detail is used as is', () => {
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} question={ASKED} onAnswer={() => {}} />)
    const labels = screen.getAllByTestId('option-label').map((l) => l.textContent ?? '')
    const details = screen.getAllByTestId('option-detail').map((d) => d.textContent)
    expect(labels).toEqual(['Voice it next turn', 'Add the four now', expect.stringMatching(/…$/)])
    expect([...labels[2]].length).toBeLessThanOrEqual(41)
    expect(details).toEqual(['Add the four finished lines now and leave 7 to 10 s quiet.', LONG])
  })

  it('sends the option as Voltage gave it, not the short label', async () => {
    const onAnswer = vi.fn()
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} question={ASKED} onAnswer={onAnswer} />)
    const buttons = within(screen.getByTestId('clarify')).getAllByRole('button')
    await userEvent.click(buttons[2])
    expect(onAnswer).toHaveBeenCalledWith(LONG)
  })

  it('says the money as one sentence: what the turn has left of its cap', () => {
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} question={ASKED} />)
    expect(screen.getByTestId('clarify-money')).toHaveTextContent('This turn has $0.00 left of its $0.50 cap.')
    expect(screen.getByTestId('clarify')).not.toHaveTextContent(/left in turn/i)
    expect(unlabelledMoney(screen.getByTestId('clarify'))).toEqual([])
  })

  it('falls back to the pane’s turn cap when the question carries none', () => {
    const { cap_usd: _c, ...older } = ASKED
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} question={older} turnCap={0.75} />)
    expect(screen.getByTestId('clarify-money')).toHaveTextContent('This turn has $0.00 left of its $0.75 cap.')
  })

  it('offers the way through the turn’s cap first; picking it asks to allow more', async () => {
    const onAnswer = vi.fn()
    const capped = {
      ...ASKED,
      options: ['Go ahead, allow $0.04 more', ...ASKED.options],
      details: ['Raises this turn’s cap to $0.54 and carries on.', ...ASKED.details],
      turn_cap: { needed_usd: 0.04, cap_usd: 0.5 },
    }
    render(<VoltagePane messages={THREAD} state="needs your go" need onSubmit={() => {}} question={capped} onAnswer={onAnswer} />)
    const buttons = within(screen.getByTestId('clarify')).getAllByRole('button')
    expect(buttons[0]).toHaveTextContent('Go ahead, allow $0.04 more')
    expect(buttons[0]).toHaveAttribute('data-option', 'allow-more')
    expect(buttons[0]).toHaveClass('volt')
    expect(buttons[1]).toHaveTextContent('Voice it next turn')
    expect(buttons[1]).toHaveAttribute('data-option', 'pick')
    await userEvent.click(buttons[0])
    expect(onAnswer).toHaveBeenCalledWith('Go ahead, allow $0.04 more', true)
    await userEvent.click(buttons[1])
    expect(onAnswer).toHaveBeenLastCalledWith('Voice it next turn')
    expect(unlabelledMoney(screen.getByTestId('clarify'))).toEqual([])
  })

  it('keeps the header on one line: the status truncates, the engine is behind an info button', async () => {
    render(<VoltagePane messages={[]} state="needs your go" need engine="Opus 5.5 · High" onSubmit={() => {}} />)
    expect(screen.getByTestId('pane-header')).toHaveClass('flex-nowrap')
    expect(screen.getByTestId('pane-status')).toHaveClass('truncate', 'min-w-0')
    expect(screen.getByTestId('pane-status')).toHaveAttribute('title', 'needs your go')
    const info = screen.getByRole('button', { name: 'Model: Opus 5.5 · High' })
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveClass('hidden')
    await userEvent.click(info)
    expect(info).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('tooltip')).toHaveTextContent('Opus 5.5 · High')
  })

  it('folds the brief and voices chips behind a Context chip on a narrow pane', async () => {
    render(<VoltagePane messages={[]} state="ready" chips={['Brief · Diwali 2026', '2 shared voices']} onSubmit={() => {}} />)
    const toggle = screen.getByTestId('context-toggle')
    expect(toggle).toHaveClass('hidden', '@max-[380px]:inline-flex')
    for (const c of screen.getAllByTestId('context-chip')) expect(c).toHaveClass('@max-[380px]:hidden')
    await userEvent.click(toggle)
    for (const c of screen.getAllByTestId('context-chip')) expect(c).not.toHaveClass('@max-[380px]:hidden')
  })

  it('never scrolls sideways: the root hides x overflow and the thread scrolls in its own area', () => {
    render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} />)
    expect(screen.getByTestId('voltage-pane')).toHaveClass('pane-root', 'min-w-0')
    expect(screen.getByRole('log')).toHaveClass('pane-thread', 'overflow-y-auto', 'min-h-0', 'flex-1')
  })

  it('scrolls new content into view only near the bottom; otherwise shows “New from Voltage ↓”', async () => {
    const more: ChatMessage[] = [...THREAD, { role: 'assistant', text: 'One more thing.', seq: 9 }]
    const { rerender } = render(<VoltagePane messages={THREAD} state="ready" onSubmit={() => {}} />)
    const log = screen.getByRole('log')
    Object.defineProperty(log, 'scrollHeight', { configurable: true, value: 2000 })
    Object.defineProperty(log, 'clientHeight', { configurable: true, value: 400 })
    log.scrollTop = 200                                // well above the bottom
    fireEvent.scroll(log)
    rerender(<VoltagePane messages={more} state="ready" onSubmit={() => {}} />)
    expect(log.scrollTop).toBe(200)
    const pill = screen.getByTestId('new-from-voltage')
    expect(pill).toHaveTextContent('New from Voltage ↓')
    await userEvent.click(pill)
    expect(screen.queryByTestId('new-from-voltage')).toBeNull()

    log.scrollTop = 1580                               // within reach of the bottom
    fireEvent.scroll(log)
    rerender(<VoltagePane messages={[...more, { role: 'assistant', text: 'And another.', seq: 10 }]} state="ready" onSubmit={() => {}} />)
    expect(log.scrollTop).toBe(2000)
    expect(screen.queryByTestId('new-from-voltage')).toBeNull()
  })
})
