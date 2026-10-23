import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  it('offers Google sign-in and says what Voltage does', () => {
    const { container } = render(<LoginPage />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Change what your video says.')
    expect(screen.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute('href', '/api/auth/login?terms=1')
    expect(screen.getByTestId('google-terms')).toHaveTextContent('Continuing with Google accepts the Terms and the Privacy notice.')
    expect(screen.getByText(/Private by default/)).toBeInTheDocument()
    expect(screen.getByText(/Videos up to 10 min/)).toBeInTheDocument()
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

describe('Accounts (launch item 5)', () => {
  const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
  const OPTIONS = { mode: 'accounts', google: false, password: true, email_link: false, invite_only: true, terms_version: 'draft' }

  it('makes an account only with the Terms accepted, and says to check the email', async () => {
    const { vi } = await import('vitest')
    const userEvent = (await import('@testing-library/user-event')).default
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.endsWith('/auth/options')) return ok(OPTIONS)
      if (url.endsWith('/auth/signup')) return ok({ sent: true, message: 'If that address can use Voltage, an email is on its way.' }, 201)
      return ok({})
    }))
    render(<LoginPage />)
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Continue with Google' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New here? Make an account' }))
    await userEvent.type(screen.getByLabelText('Email'), 'ann@example.com')
    await userEvent.type(screen.getByLabelText(/^Password/), 'correct horse battery')
    await userEvent.type(screen.getByLabelText(/Invite code/), 'LAUNCH-42')
    const make = screen.getByRole('button', { name: 'Make my account' })
    expect(make).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(make)
    expect(await screen.findByTestId('auth-notice')).toHaveTextContent('an email is on its way')
    expect(calls).toContain('POST /api/auth/signup {"email":"ann@example.com","password":"correct horse battery","accept_terms":true,"invite_code":"LAUNCH-42"}')
    vi.unstubAllGlobals()
  })

  it('offers to send the confirmation again when the address is not confirmed', async () => {
    const { vi } = await import('vitest')
    const userEvent = (await import('@testing-library/user-event')).default
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/auth/options')) return ok(OPTIONS)
      if (url.endsWith('/auth/password/login')) return ok({ detail: { code: 'unverified', message: 'Confirm your email first: open the link we sent.' } }, 403)
      if (url.endsWith('/auth/verify/resend')) return ok({ sent: true, message: 'An email is on its way.' })
      return ok({})
    }))
    render(<LoginPage />)
    await userEvent.type(await screen.findByLabelText('Email'), 'ann@example.com')
    await userEvent.type(screen.getByLabelText(/^Password/), 'correct horse battery')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Confirm your email first')
    await userEvent.click(screen.getByRole('button', { name: 'Send the confirmation link again' }))
    expect(await screen.findByTestId('auth-notice')).toHaveTextContent('An email is on its way.')
    vi.unstubAllGlobals()
  })
})
