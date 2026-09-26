import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SpendMeter } from './SpendMeter'

const USAGE = {
  spent_usd: 0.0412, ceiling_usd: 2, voice_characters: 120, voice_characters_ceiling: 2000,
  lines: [{ vendor: 'anthropic', what: 'intent', unit: 'tokens', units: 1200, usd: 0.01, calls: 1 }],
}

describe('SpendMeter', () => {
  it('shows spend and voice characters against their limits', () => {
    render(<SpendMeter usage={USAGE} />)
    expect(screen.getByTestId('spend')).toHaveTextContent(
      'Spent ≈ $0.04 of $2.00 · voice 120 / 2,000 characters')
    expect(screen.getByTestId('spend')).toHaveAttribute('title', 'Reading requests: $0.010 (1×)')
  })

  it('shows nothing before usage has loaded', () => {
    const { container } = render(<SpendMeter usage={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
