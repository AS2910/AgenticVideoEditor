import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QuestionCard, withPrice } from './QuestionCard'
import type { PlanQuestion } from '../types'

/** Run 5 item 2: one card per question, one primary button; a pick is the approval. */
describe('QuestionCard', () => {
  it('a gate has one primary button, named for the step with its price', async () => {
    const onAnswer = vi.fn()
    const gate: PlanQuestion = { text: 'Voice “Get 30% off.” in Ana\'s voice, about $0.30?', options: ['Voice it · $0.30', 'Not yet'], guess: 'Voice it · $0.30', gate: true, cost_usd: 0.3, left_usd: 0.4, cap_usd: 0.5 }
    render(<QuestionCard question={gate} onAnswer={onAnswer} />)
    const primary = document.querySelectorAll('[data-primary]')
    expect(primary).toHaveLength(1)
    expect(primary[0]).toHaveTextContent('Voice it · $0.30')
    await userEvent.click(screen.getByRole('button', { name: /Voice it · \$0\.30/ }))
    expect(onAnswer).toHaveBeenCalledWith('Voice it · $0.30')
  })

  it('a meaning question that leads to a paid step carries the price on Voltage\'s pick, and the pick sends the option as given', async () => {
    const onAnswer = vi.fn()
    const q: PlanQuestion = { text: 'Where should the new line go?', options: ['After line 3', 'Voice it here'], guess: 'Voice it here', gate: false, cost_usd: 0.04, details: [null, 'After line 2, over the beach.'] }
    render(<QuestionCard question={q} onAnswer={onAnswer} />)
    const primary = document.querySelectorAll('[data-primary]')
    expect(primary).toHaveLength(1)
    expect(primary[0]).toHaveTextContent('Voice it here · $0.04')
    expect(screen.getByTestId('clarify-status')).toHaveTextContent('Your pick is your go.')
    await userEvent.click(primary[0] as HTMLElement)
    expect(onAnswer).toHaveBeenCalledWith('Voice it here')
  })

  it('a question about meaning with nothing paid after it shows no price', () => {
    const q: PlanQuestion = { text: 'Which voice?', options: ['Ana', 'Ben'], guess: 'Ana', gate: false }
    render(<QuestionCard question={q} />)
    expect(document.querySelector('[data-primary]')).toHaveTextContent('Ana')
    expect(screen.queryByText(/\$/)).toBeNull()
  })

  it('withPrice leaves a label that names a price, a gate and a secondary option alone', () => {
    const q: PlanQuestion = { text: 'Q', options: ['A', 'B'], guess: 'A', gate: false, cost_usd: 0.04 }
    expect(withPrice('Voice it here · $0.04', q, true)).toBe('Voice it here · $0.04')
    expect(withPrice('B', q, false)).toBe('B')
    expect(withPrice('A', { ...q, gate: true }, true)).toBe('A')
    expect(withPrice('A', q, true)).toBe('A · $0.04')
  })
})
