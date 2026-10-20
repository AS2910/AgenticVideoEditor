import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectPage } from './ProjectPage'
import { BriefDiff } from './BriefVersions'
import { resetFlags } from '../flags/useFlags'
import { agoLabel } from '../lib/dates'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const ME = { mode: 'off' as const, user: null }
const NOW = Date.now()
const DAYS_AGO = (n: number) => new Date(NOW - n * 86_400_000).toISOString()

const PROJECT = { project_id: 'f1', name: 'Diwali 2026', brief: 'Get 30% off.', settings: { autonomy: 'ask' }, ceiling_usd: null, spent_usd: 0, created_at: DAYS_AGO(9),
  brief_version: 4, brief_edited_by: 'local', brief_edited_at: DAYS_AGO(2), stale_count: 1 }
const VIDEOS = [
  { video_id: 'p2', project_id: 'f1', filename: 'bhaji-cam-ad.mp4', duration: 48.9, created_at: DAYS_AGO(5), edits: 1, state: 'shipped', made_with_brief: 3, brief_changed: true },
  { video_id: 'p3', project_id: 'f1', filename: 'shop-tour.mp4', duration: 31, created_at: DAYS_AGO(5), edits: 0, state: 'new', made_with_brief: null, brief_changed: false },
]
const VERSIONS = [
  { project_id: 'f1', version: 4, text: 'Get 30% off.', created_by: 'local', created_at: DAYS_AGO(2) },
  { project_id: 'f1', version: 3, text: 'Get 20% off.', created_by: 'local', created_at: DAYS_AGO(4) },
]
const RUN = (status: 'running' | 'finished') => ({ run_id: 'u1', to: 4, status, started_at: DAYS_AGO(0), finished_at: status === 'finished' ? DAYS_AGO(0) : null, videos: [
  status === 'running'
    ? { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', from: 3, job_id: 'J9', status: 'running', step: 'Voltage is on it', outcome: null, why: null }
    : { video_id: 'p2', filename: 'bhaji-cam-ad.mp4', from: 3, job_id: 'J9', status: 'done', step: 'Ready to review', outcome: 'proposed', why: '1 line is ready to hear. Add them in the video.' },
] })

function routeFetch(calls: string[], flags = ['projects.consistency']) {
  let run: unknown = null
  let reads = 0
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push(`${method} ${url}`)
    if (url.endsWith('/me/flags')) return ok({ flags })
    if (url.endsWith('/projects/f1') && method === 'GET') return ok({ project: PROJECT, videos: VIDEOS, voices: [], files: [], suggestions: [] })
    if (url.includes('/spend?project=f1')) return ok({ project: null, month: null, binding: null })
    if (url.endsWith('/projects/f1/briefs')) return ok({ current: 4, versions: VERSIONS })
    if (url.includes('/projects/f1/briefs/diff')) return ok({ a: 3, b: 4, changes: [{ op: 'same', text: 'Get ' }, { op: 'removed', text: '20%' }, { op: 'added', text: '30%' }, { op: 'same', text: ' off.' }] })
    if (url.endsWith('/projects/f1/brief-update') && method === 'POST') { run = RUN('running'); return ok({ run }, 202) }
    if (url.endsWith('/projects/f1/brief-update')) { if (run) { reads += 1; if (reads > 1) run = RUN('finished') } return ok({ run }) }
    throw new Error(`unexpected ${method} ${url}`)
  })
}

describe('A1: brief versions and stale videos on the project page', () => {
  beforeEach(() => { resetFlags(); window.location.hash = '#p/f1' })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); window.location.hash = '' })

  it('says the version, who saved it and when, and opens the history with a word diff', async () => {
    vi.stubGlobal('fetch', routeFetch([]))
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    expect(await screen.findByText('v4 · edited by you, 2 days ago')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'History' }))
    const history = await screen.findByRole('region', { name: 'Brief history' })
    expect(await within(history).findByText('Get 20% off.')).toBeInTheDocument()
    const diff = await within(history).findByTestId('brief-diff')
    expect(diff.querySelector('del')).toHaveTextContent('20%')
    expect(diff.querySelector('ins')).toHaveTextContent('30%')
  })

  it('marks the stale video and brings it up to date, saying how each ended', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', routeFetch(calls))
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    const chips = await screen.findAllByTestId('brief-changed')
    expect(chips).toHaveLength(1)
    expect(screen.getByTestId('stale-line')).toHaveTextContent('1 video made with an older brief')
    await userEvent.click(screen.getByRole('button', { name: 'Bring up to date' }))
    expect(calls).toContain('POST /api/projects/f1/brief-update')
    expect(await screen.findByText('Bringing 1 video up to v4')).toBeInTheDocument()
    expect(within(screen.getByTestId('brief-run')).getByText('Voltage is on it')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Brought up to v4')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.getByText('Ready to review')).toBeInTheDocument()
    expect(screen.getByText('1 line is ready to hear. Add them in the video.')).toBeInTheDocument()
  })

  it('shows none of it with the flag off', async () => {
    vi.stubGlobal('fetch', routeFetch([], []))
    render(<ProjectPage me={ME} projectId="f1" onUpload={() => {}} />)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Diwali 2026')
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByTestId('brief-meta')).toBeNull()
    expect(screen.queryByTestId('brief-changed')).toBeNull()
    expect(screen.queryByTestId('stale-line')).toBeNull()
  })
})

describe('BriefDiff and agoLabel', () => {
  it('says when two versions are the same', () => {
    render(<BriefDiff changes={[{ op: 'same', text: 'Bright.' }]} />)
    expect(screen.getByText('These two versions say the same thing.')).toBeInTheDocument()
  })
  it('counts minutes, hours and days', () => {
    const now = new Date('2026-10-21T12:00:00Z')
    expect(agoLabel('2026-10-21T11:59:40Z', now)).toBe('just now')
    expect(agoLabel('2026-10-21T11:55:00Z', now)).toBe('5 minutes ago')
    expect(agoLabel('2026-10-21T09:00:00Z', now)).toBe('3 hours ago')
    expect(agoLabel('2026-10-20T09:00:00Z', now)).toBe('yesterday')
    expect(agoLabel('2026-10-19T09:00:00Z', now)).toBe('2 days ago')
  })
})
