import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  it('offers Google sign-in and says what Voltage does', () => {
    const { container } = render(<LoginPage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Change what your video says.')
    expect(screen.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute('href', '/api/auth/login')
    expect(screen.getByText(/Private by default/)).toBeInTheDocument()
    expect(screen.getByText(/Videos up to 3 min/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // The right pane is a picture of Voltage at work, hidden from assistive tech.
    const pane = screen.getByText(/voicing line 1/).closest('section')!
    expect(pane).toHaveAttribute('aria-hidden', 'true')
    expect(container.querySelector('del')).toHaveTextContent('20%')
    expect(container.querySelectorAll('ins')[1]).toHaveTextContent('30%')
  })

  it('shows why you are back at the door', () => {
    render(<LoginPage error="Your session ended. Sign in again to continue." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Your session ended.')
  })
})
