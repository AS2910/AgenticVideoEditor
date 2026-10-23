import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsPage } from './SettingsPage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const SETTINGS = { autonomy: 'ask', turn_usd: 0.5, effort: 'high', ask_before: { ship: false, clone: true, design: false } }
const REPORT = { period: 'month', spent_usd: 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14, by_vendor: [], by_project: [] }
const ME = { mode: 'google' as const, user: { sub: '1', email: 'ashish@example.com', name: 'Ashish Sinha', picture: null } }

type Call = { url: string; method: string; body: Record<string, unknown> | undefined }
function routeFetch() {
  const calls: Call[] = []
  let settings: Record<string, unknown> = SETTINGS
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    if (method !== 'GET') calls.push({ url, method, body })
    if (url.endsWith('/me/settings') && method === 'GET') return ok(settings)
    if (url.endsWith('/me/settings') && method === 'PUT') { settings = { ...settings, ...body }; return ok(settings) }
    if (url.includes('/usage?period=month')) return ok(REPORT)
    if (url.endsWith('/auth/logout')) return ok({ signed_out: true })
    if (url.endsWith('/account') && method === 'DELETE') return ok({})
    throw new Error(`unexpected ${method} ${url}`)
  })
  vi.stubGlobal('fetch', f)
  return calls
}

describe('SettingsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.location.hash = ''
    window.localStorage.removeItem('voltage-theme')
    document.documentElement.classList.remove('dark')
  })

  it('shows the defaults, and saves a switch the moment it is flipped', async () => {
    const calls = routeFetch()
    render(<SettingsPage me={ME} onSignedOut={() => {}} />)
    expect(await screen.findByRole('radio', { name: /Check with me/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('turn-cap')).toHaveTextContent('$0.50')
    expect(screen.getByText('Project ceiling').parentElement!.parentElement).toHaveTextContent('$2.00')
    expect(screen.getByRole('button', { name: 'High' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('switch', { name: 'Cloning a speaker' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: 'Exporting the video' })).toHaveAttribute('aria-checked', 'false')
    const del = screen.getByRole('switch', { name: 'Deleting a voice' })
    expect(del).toHaveAttribute('aria-checked', 'true')
    expect(del).toBeDisabled()

    await userEvent.click(screen.getByRole('switch', { name: 'Exporting the video' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/me/settings', method: 'PUT', body: { ask_before: { ship: true, clone: true, design: false } } }))
    expect(screen.getByRole('switch', { name: 'Exporting the video' })).toHaveAttribute('aria-checked', 'true')
    expect(await screen.findByRole('status')).toHaveTextContent('Saved')
  })

  it('steps the turn cap by 10¢, and saves autonomy and effort', async () => {
    const calls = routeFetch()
    render(<SettingsPage me={ME} onSignedOut={() => {}} />)
    await screen.findByTestId('turn-cap')
    await userEvent.click(screen.getByRole('button', { name: 'Raise the turn cap' }))
    expect(screen.getByTestId('turn-cap')).toHaveTextContent('$0.60')
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/me/settings', method: 'PUT', body: { turn_usd: 0.6 } }))
    await userEvent.click(screen.getByRole('radio', { name: /Just do it/ }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/me/settings', method: 'PUT', body: { autonomy: 'draft' } }))
    expect(screen.getByRole('radio', { name: /Just do it/ })).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Extra' }))
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/me/settings', method: 'PUT', body: { effort: 'xhigh' } }))
    // An unchanged choice is not sent again.
    await userEvent.click(screen.getByRole('button', { name: 'Extra' }))
    expect(calls.filter((c) => c.body?.effort).length).toBe(1)
  })

  it('switches the theme', async () => {
    routeFetch()
    render(<SettingsPage me={ME} onSignedOut={() => {}} />)
    expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Dark' }))
    expect(document.documentElement).toHaveClass('dark')
    expect(window.localStorage.getItem('voltage-theme')).toBe('dark')
  })

  it('signs out, and deletes everything only after DELETE is typed', async () => {
    const calls = routeFetch()
    const onSignedOut = vi.fn()
    render(<SettingsPage me={ME} onSignedOut={onSignedOut} />)
    expect(await screen.findByText('Ashish Sinha')).toBeInTheDocument()
    expect(screen.getByText('Signed in with Google')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(onSignedOut).toHaveBeenCalledOnce())
    expect(calls).toContainEqual({ url: '/api/auth/logout', method: 'POST', body: undefined })
    expect(window.location.hash).toBe('#home')

    await userEvent.click(screen.getByRole('button', { name: 'Delete…' }))
    const go = screen.getByRole('button', { name: 'Delete everything' })
    expect(go).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Type DELETE to confirm/), 'DELETE')
    expect(go).toBeEnabled()
    await userEvent.click(go)
    await waitFor(() => expect(calls).toContainEqual({ url: '/api/account', method: 'DELETE', body: undefined }))
    await waitFor(() => expect(onSignedOut).toHaveBeenCalledTimes(2))
  })

  it('says sign-in is off, with no way out, on a local build', async () => {
    routeFetch()
    render(<SettingsPage me={{ mode: 'off', user: null }} onSignedOut={() => {}} />)
    expect(await screen.findByText('Local, sign-in is off')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Account' })).toHaveTextContent('V')
  })

  it('names how an email-and-password account signed in (rehearsal item 7)', async () => {
    routeFetch()
    render(<SettingsPage me={{ mode: 'accounts', user: { sub: 'a1', email: 'ann@x.io', name: null, picture: null, provider: 'acct' } }} onSignedOut={() => {}} />)
    expect(await screen.findByText('Signed in with your email and password')).toBeInTheDocument()
    expect(screen.queryByText('Local, sign-in is off')).toBeNull()
  })
})
