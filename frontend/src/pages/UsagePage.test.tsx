import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UsagePage } from './UsagePage'
import { unlabelledMoney } from '../lib/money'

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body, text: async () => '' }) as Response
const GROUPS = [
  { project_id: 'f1', name: 'Diwali 2026', ceiling_usd: 10, project_level_usd: 0.09, spent_usd: 1.4, videos: [
    { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', spent_usd: 1.07, here: true },
    { video_id: 'p3', filename: 'shop-tour.mp4', spent_usd: 0.24, here: false },
  ] },
  { project_id: 'f2', name: 'Goa tourism', ceiling_usd: null, project_level_usd: 0, spent_usd: 0.24, videos: [{ video_id: 'p3', filename: 'shop-tour.mp4', spent_usd: 0.24, here: true }] },
  { project_id: null, name: 'No project', ceiling_usd: null, project_level_usd: null, spent_usd: 0.42, videos: [{ video_id: 'p1', filename: 'goa-beach.mov', spent_usd: 0.42, here: true }] },
]
const VENDORS = [{ vendor: 'anthropic', label: 'Voltage thinking', usd: 1.31 }, { vendor: 'elevenlabs', label: 'Voices and takes', usd: 0.75 }]
const TOTALS: Record<string, unknown> = {
  all: { scope: 'all', label: 'October', spent_usd: 2.06, ceiling_usd: 10, by_vendor: VENDORS },
  f1: { scope: 'f1', label: 'Project Diwali 2026', spent_usd: 1.4, ceiling_usd: 10, by_vendor: [{ vendor: 'elevenlabs', label: 'Voices and takes', usd: 1.4 }] },
  none: { scope: 'none', label: 'Standalone videos', spent_usd: 0.42, ceiling_usd: null, by_vendor: [{ vendor: 'openai', label: 'Transcription', usd: 0.42 }] },
  'v:p3': { scope: 'v:p3', label: 'shop-tour.mp4', spent_usd: 0.48, ceiling_usd: 2, by_vendor: [{ vendor: 'elevenlabs', label: 'Voices and takes', usd: 0.48 }] },
}
const report = (period: string, scope: string) => ({
  period, spent_usd: period === 'week' ? 1.12 : 2.06, ceiling_usd: 10, project_cap_usd: 2, turns: period === 'week' ? 9 : 16, takes: 14, voices_made: 3, avg_turn_usd: 0.14,
  by_vendor: VENDORS, by_video: [], by_project: [], groups: GROUPS,
  totals: period === 'week' && scope === 'all' ? { scope: 'all', label: 'Last 7 days', spent_usd: 1.12, ceiling_usd: null, by_vendor: VENDORS } : TOTALS[scope],
})
function routeFetch() {
  const f = vi.fn(async (url: string) => {
    const m = /\/usage\?period=(\w+)(?:&scope=([^&]+))?/.exec(url)
    if (m) return ok(report(m[1], m[2] ? decodeURIComponent(m[2]) : 'all'))
    throw new Error(`unexpected url ${url}`)
  })
  vi.stubGlobal('fetch', f)
  return f
}
const ME = { mode: 'off' as const, user: null }

describe('UsagePage', () => {
  afterEach(() => { vi.unstubAllGlobals(); window.location.hash = '' })

  it('holds the space with a sentence, then shows the month’s totals, labelled, from the report', async () => {
    routeFetch()
    render(<UsagePage me={ME} />)
    expect(screen.getByRole('status')).toHaveTextContent(/Adding up/)
    expect(screen.getByTestId('spent')).toHaveTextContent('…')
    expect(await screen.findByText('$2.06')).toBeInTheDocument()
    const totals = screen.getByTestId('totals')
    expect(totals).toHaveAttribute('data-money-scope', 'month')
    expect(totals).toHaveTextContent('Spent · October')
    expect(totals).toHaveTextContent('of your $10 monthly ceiling')
    expect(screen.getByRole('meter', { name: 'October: spent against its ceiling' })).toHaveAttribute('aria-valuenow', '21')
    expect(screen.getByText('Turns', { selector: 'div' }).nextElementSibling).toHaveTextContent('16')
    expect(screen.getByText('Avg turn', { selector: 'div' }).nextElementSibling).toHaveTextContent('$0.14')
    expect(screen.getByText('Voltage thinking')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Your plan and monthly ceiling' })).toHaveAttribute('href', '#billing')
    expect(screen.getByRole('link', { name: 'Usage' })).toHaveAttribute('aria-current', 'page')
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('shows projects as rows with their videos nested and expandable, a Project-level row, and No project', async () => {
    routeFetch()
    render(<UsagePage me={ME} />)
    await screen.findByText('$2.06')
    const table = screen.getByTestId('usage-table')
    expect(within(table).getByRole('link', { name: 'Diwali 2026' })).toHaveAttribute('href', '#p/f1')
    expect(within(table).getByRole('link', { name: 'No project' })).toHaveAttribute('href', '#usage/none')
    // Folded until opened.
    expect(within(table).queryByRole('link', { name: 'bhaji-cam-ad.mp4' })).toBeNull()
    await userEvent.click(within(table).getByRole('button', { name: 'Open Diwali 2026' }))
    expect(within(table).getByRole('link', { name: 'bhaji-cam-ad.mp4' })).toHaveAttribute('href', '#v/p2')
    expect(screen.getByTestId('row-f1-p3')).toHaveTextContent('moved out · spent while here')
    expect(screen.getByTestId('row-f1-p3')).toHaveTextContent('$0.24')
    expect(screen.getByTestId('project-level-f1')).toHaveTextContent('Project-level')
    expect(screen.getByTestId('project-level-f1')).toHaveTextContent('$0.09')
    await userEvent.click(within(table).getByRole('button', { name: 'Open No project' }))
    expect(within(table).getByRole('link', { name: 'goa-beach.mov' })).toHaveAttribute('href', '#v/p1')
    expect(screen.queryByTestId('project-level-none')).toBeNull()
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('switches scope: a project, the standalone videos, back to all, and the totals follow', async () => {
    const f = routeFetch()
    render(<UsagePage me={ME} />)
    await screen.findByText('$2.06')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Project' }), 'f1')
    await waitFor(() => expect(f).toHaveBeenCalledWith(expect.stringContaining('/usage?period=month&scope=f1')))
    expect(window.location.hash).toBe('#usage/p/f1')
    await waitFor(() => expect(screen.getByTestId('totals')).toHaveTextContent('Spent · Project Diwali 2026'))
    expect(screen.getByTestId('totals')).toHaveAttribute('data-money-scope', 'project')
    expect(screen.getByTestId('totals')).toHaveTextContent('of its $10 project ceiling')
    expect(screen.queryByTestId('group-none')).toBeNull()
    expect(screen.getByRole('link', { name: 'bhaji-cam-ad.mp4' })).toBeInTheDocument()   // a filtered table is open

    await userEvent.click(screen.getByRole('button', { name: 'Standalone videos' }))
    await waitFor(() => expect(screen.getByTestId('totals')).toHaveTextContent('Spent · Standalone videos'))
    expect(screen.getByTestId('totals')).toHaveTextContent('no ceiling of its own')
    expect(window.location.hash).toBe('#usage/none')
    expect(screen.queryByTestId('group-f1')).toBeNull()
    expect(unlabelledMoney(document.body)).toEqual([])

    await userEvent.click(screen.getByRole('button', { name: 'All' }))
    await waitFor(() => expect(screen.getByTestId('totals')).toHaveTextContent('Spent · October'))
    expect(window.location.hash).toBe('#usage')
  })

  it('opens filtered to one video from the editor, under every project it spent in', async () => {
    const f = routeFetch()
    render(<UsagePage me={ME} scope={{ kind: 'video', id: 'p3' }} />)
    await waitFor(() => expect(f).toHaveBeenCalledWith(expect.stringContaining('scope=v%3Ap3')))
    await waitFor(() => expect(screen.getByTestId('totals')).toHaveTextContent('Spent · shop-tour.mp4'))
    expect(screen.getByTestId('totals')).toHaveTextContent('of its $2 video ceiling')
    expect(screen.getByTestId('row-f1-p3')).toBeInTheDocument()
    expect(screen.getByTestId('row-f2-p3')).toBeInTheDocument()
    expect(screen.queryByTestId('row-f1-p2')).toBeNull()
    expect(screen.queryByTestId('group-none')).toBeNull()
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('refetches when the period changes', async () => {
    const f = routeFetch()
    render(<UsagePage me={ME} />)
    await screen.findByText('$2.06')
    await userEvent.click(screen.getByRole('button', { name: 'Week' }))
    expect(screen.getByRole('button', { name: 'Week' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(f).toHaveBeenCalledWith(expect.stringContaining('/usage?period=week')))
    expect(await screen.findByText('$1.12')).toBeInTheDocument()
    expect(screen.getByText('Spent · Last 7 days')).toBeInTheDocument()
  })

  it('lists paused and stopped turns with their real cost (addendum 3.5)', async () => {
    const ended = [
      { video_id: 'p1', filename: 'goa-beach.mov', turn_id: 'j4', state: 'paused', label: 'Paused', spent_usd: 0.06, at: '2026-10-28T10:05:00Z' },
      { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', turn_id: 'j2', state: 'stopped', label: 'Stopped', spent_usd: 0.11, at: '2026-10-28T10:00:00Z' },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => ok({ ...report('month', 'all'), ended_early: ended })))
    render(<UsagePage me={ME} />)
    const rows = await screen.findAllByTestId('ended-turn')
    expect(rows.map((r) => r.textContent)).toEqual([
      'Pausedgoa-beach.movturn waiting for Resume$0.06', 'Stoppedbhaji-cam-ad.mp4turn$0.11',
    ])
    expect(screen.getByRole('heading', { name: 'Paused and stopped turns' })).toBeInTheDocument()
    expect(unlabelledMoney(document.body)).toEqual([])
  })

  it('says when the report cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}), text: async () => JSON.stringify({ detail: 'The ledger is away.' }) }) as Response))
    render(<UsagePage me={ME} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The ledger is away.')
  })
})
