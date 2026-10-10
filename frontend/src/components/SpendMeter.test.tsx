import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SpendMeter } from './SpendMeter'

const USAGE = {
  spent_usd: 0.0412, ceiling_usd: 2, voice_characters: 120, voice_characters_ceiling: 2000,
  lines: [{ vendor: 'anthropic', what: 'intent', unit: 'tokens', units: 1200, usd: 0.01, calls: 1 }],
}

describe('SpendMeter', () => {
  it('shows spend and voice characters against their limits', () => {
    render(<SpendMeter usage={USAGE} />)
    expect(screen.getByTestId('spend')).toHaveTextContent('$0.04 of $2.00 120 of 2,000 voice characters')
    expect(screen.getByRole('meter', { name: 'Spend against the cap' })).toHaveAttribute('aria-valuenow', '0.0412')
    expect(screen.getByTestId('spend')).not.toHaveAttribute('title')
  })

  it('opens the breakdown as a popover, and Escape closes it with focus back on the meter', async () => {
    const user = userEvent.setup()
    render(<SpendMeter usage={{ ...USAGE, user_spent_usd: 0.5, user_ceiling_usd: 5 }} />)
    const meter = screen.getByTestId('spend')
    expect(meter).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('spend-breakdown')).not.toBeInTheDocument()

    await user.click(meter)
    expect(meter).toHaveAttribute('aria-expanded', 'true')
    const pop = screen.getByRole('dialog', { name: 'Spend breakdown' })
    expect(pop).toHaveTextContent('Reading requests$0.010 · 1 call')
    expect(pop).toHaveTextContent('Voice characters120 of 2,000')
    expect(pop).toHaveTextContent('You, across projects$0.50 of $5.00')

    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('spend-breakdown')).not.toBeInTheDocument()
    expect(meter).toHaveFocus()
  })

  it('closes on a click outside', async () => {
    const user = userEvent.setup()
    render(<div><SpendMeter usage={USAGE} /><p>elsewhere</p></div>)
    await user.click(screen.getByTestId('spend'))
    expect(screen.getByTestId('spend-breakdown')).toBeInTheDocument()
    await user.click(screen.getByText('elsewhere'))
    expect(screen.queryByTestId('spend-breakdown')).not.toBeInTheDocument()
  })

  it('shows nothing before usage has loaded', () => {
    const { container } = render(<SpendMeter usage={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
