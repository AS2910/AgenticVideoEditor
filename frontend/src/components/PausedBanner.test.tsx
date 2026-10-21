import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PausedBanner } from './PausedBanner'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response

describe('PausedBanner (launch item 3)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says paid work is paused while the server says so', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ paid_paused: true, message: 'Voltage is pausing new paid work for a little while.', resumes_at: null })))
    render(<PausedBanner />)
    expect(await screen.findByTestId('paused-banner')).toHaveTextContent('Voltage is pausing new paid work for a little while.')
  })

  it('shows nothing otherwise, or when the status cannot be read', async () => {
    const fetch = vi.fn(async () => ok({ paid_paused: false, message: null }))
    vi.stubGlobal('fetch', fetch)
    const { unmount } = render(<PausedBanner />)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('paused-banner')).not.toBeInTheDocument()
    unmount()
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    render(<PausedBanner />)
    expect(screen.queryByTestId('paused-banner')).not.toBeInTheDocument()
  })
})
