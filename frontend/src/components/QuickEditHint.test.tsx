import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QuickEditHint } from './QuickEditHint'

describe('QuickEditHint (run 5 item 6)', () => {
  it('says nothing until the words change', () => {
    const { container } = render(<QuickEditHint before="Get 20% off today only." after="Get 20% off today only." voiceChanged={false} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('says a small change in the line\'s own voice is voiced straight away', () => {
    render(<QuickEditHint before="Fresh bread every single morning." after="Warm rolls every Sunday afternoon." voiceChanged={false} />)
    const hint = screen.getByTestId('quick-edit-hint')
    expect(hint).toHaveAttribute('data-route', 'fast')
    expect(hint).toHaveTextContent('Small change: Enter voices it straight away.')
  })
  it('says Voltage plans a bigger change or a new voice', () => {
    render(<QuickEditHint before="Get 20% off today." after="Get thirty percent off every single thing in the shop until Sunday." voiceChanged={false} />)
    expect(screen.getByTestId('quick-edit-hint')).toHaveTextContent(/^Voltage will plan this one \(\d+ words changed\)\.$/)
  })
  it('says so for a new voice even with the words as they were', () => {
    render(<QuickEditHint before="a b" after="a b" voiceChanged />)
    expect(screen.getByTestId('quick-edit-hint')).toHaveTextContent('Voltage will plan this one (a different voice).')
  })
})
