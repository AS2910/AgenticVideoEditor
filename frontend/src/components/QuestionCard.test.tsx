import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QuestionCard } from './QuestionCard'
import type { Question } from '../types'

const QUESTION: Question = {
  type: 'question',
  question: 'The line is 0.74s but the selection is 3.87s. How should it fill the selection?',
  text: 'Thirsty Thirsty',
  mix: 'layer',
  options: [
    { label: "Start at the selection's start", fit: 'start', mix: null, warning: null },
    { label: 'Slow it down to fill (0.19× speed)', fit: 'stretch', mix: null,
      warning: 'It will sound dragged.' },
  ],
}

describe('QuestionCard', () => {
  it('shows the line and every option, with its warning', () => {
    render(<QuestionCard question={QUESTION} onChoose={() => {}} />)
    expect(screen.getByText('“Thirsty Thirsty”')).toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(2)
    expect(screen.getByText('It will sound dragged.')).toBeInTheDocument()
  })

  it('reports the chosen option', async () => {
    const onChoose = vi.fn()
    render(<QuestionCard question={QUESTION} onChoose={onChoose} />)
    await userEvent.click(screen.getByText(/slow it down/i))
    expect(onChoose).toHaveBeenCalledWith(QUESTION.options[1])
  })
})
