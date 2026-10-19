import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UsagePage } from './UsagePage'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const report = (period: string) => ({
  period, spent_usd: period === 'week' ? 1.12 : 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: period === 'week' ? 9 : 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14,
  by_vendor: [{ vendor: 'Claude', label: 'Voltage thinking', usd: 1.31 }, { vendor: 'ElevenLabs', label: 'Voices and takes', usd: 0.7 }],
  by_video: [{ video_id: 'p2', filename: 'bhaji-cam-ad.mp4', turns: 5, voice_characters: 612, spent_usd: 1.07, cap_usd: 2 }],
})
function routeFetch() {
  const f = vi.fn(async (url: string) => {
    const m = /\/usage\?period=(\w+)/.exec(url)
    if (m) return ok(report(m[1]))
    throw new Error(`unexpected url ${url}`)
  })
  vi.stubGlobal('fetch', f)
  return f
}
const ME = { mode: 'off' as const, user: null }

describe('UsagePage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('holds the space with a sentence, then shows the month’s figures from the report', async () => {
    routeFetch()
    render(<UsagePage me={ME} />)
    expect(screen.getByRole('status')).toHaveTextContent(/Adding up/)
    expect(screen.getByTestId('spent')).toHaveTextContent('—')
    expect(await screen.findByText('$2.06')).toBeInTheDocument()
    expect(screen.getByText('of your $10.00 monthly ceiling')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Spent against the monthly ceiling' })).toHaveAttribute('aria-valuenow', '21')
    expect(screen.getByText('Turns', { selector: 'div' }).nextElementSibling).toHaveTextContent('16')
    expect(screen.getByText('Takes voiced', { selector: 'div' }).nextElementSibling).toHaveTextContent('14')
    expect(screen.getByText('Voices made', { selector: 'div' }).nextElementSibling).toHaveTextContent('3')
    expect(screen.getByText('Avg turn', { selector: 'div' }).nextElementSibling).toHaveTextContent('$0.14')
    expect(screen.getByText('Voltage thinking')).toBeInTheDocument()
    expect(screen.getByText('$1.31')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'bhaji-cam-ad.mp4' })).toHaveAttribute('href', '#v/p2')
    expect(screen.getByText('612')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Raise the ceiling' })).toHaveAttribute('href', '#billing')
    expect(screen.getByRole('link', { name: 'Usage' })).toHaveAttribute('aria-current', 'page')
  })

  it('refetches when the period changes', async () => {
    const f = routeFetch()
    render(<UsagePage me={ME} />)
    await screen.findByText('$2.06')
    await userEvent.click(screen.getByRole('button', { name: 'Week' }))
    expect(screen.getByRole('button', { name: 'Week' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(f).toHaveBeenCalledWith(expect.stringContaining('/usage?period=week')))
    expect(await screen.findByText('$1.12')).toBeInTheDocument()
    expect(screen.getByText('Spent · This week')).toBeInTheDocument()
  })

  it('says when the report cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}), text: async () => JSON.stringify({ detail: 'The ledger is away.' }) }) as Response))
    render(<UsagePage me={ME} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The ledger is away.')
  })
})
