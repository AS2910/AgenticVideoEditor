import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BatchPanel } from './BatchPanel'
import { gateLine } from '../lib/batch'
import type { ProjectSummary } from '../types'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const fail = (detail: string, status = 409) => ({ ok: false, status, json: async () => ({ detail }), text: async () => JSON.stringify({ detail }) }) as Response
const video = (n: number, stage = 'draft') => ({ video_id: `p${n}`, project_id: 'f1', filename: `ad${n}.mp4`, duration: 10, created_at: '2026-10-20T00:00:00Z', edits: 0, stage }) as unknown as ProjectSummary
const row = (n: number, state: string, label: string, more: Record<string, unknown> = {}) => ({
  video_id: `p${n}`, filename: `ad${n}.mp4`, stage: 'draft', stage_label: 'Draft', lines: 2, est_usd: 0.08, cap_usd: 0.5, job_id: `J${n}`,
  why: null, question: null, ready: 0, spent_usd: 0, added: null, answers: [], state, label, ...more })
const batch = (phase: string, rows: unknown[], more: Record<string, unknown> = {}) => ({
  batch_id: 'J9', project_id: 'f1', source: 'ask', goal: 'Make it 30% off', phase, status: phase === 'gate' ? 'queued' : phase === 'running' ? 'running' : 'done',
  step: phase === 'running' ? '1 of 3 videos finished' : '3 of 3 videos finished', created_at: '2026-10-21T00:00:00Z', started_at: phase === 'gate' ? null : '2026-10-21T00:00:01Z',
  finished_at: null, totals: { videos: 3, lines: 6, est_usd: 0.42, est_s: 120, cap_usd: 1.5 }, summary: null, rows, counts: {}, spent_usd: 0.12, can_add: false, ...more })

function server(pages: unknown[], extra: (method: string, url: string) => Response | null = () => null) {
  const calls: string[] = []
  let k = 0
  // What a later read returns: the batch the last change answered with (the panel reads again after each).
  let latest: unknown = null
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push(`${method} ${url}${init?.body ? ` ${init.body}` : ''}`)
    if (url.endsWith('/me/onboarding')) return ok({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-batch'], checklist: [], checklist_hidden: true })
    const other = extra(method, url)
    if (other) {
      if (other.ok && method === 'POST') latest = await other.json()
      return other
    }
    if (url.endsWith('/projects/f1/batches') && method === 'GET') return ok({ batches: latest ? [latest] : pages[Math.min(k++, pages.length - 1)] })
    throw new Error(`unexpected ${method} ${url}`)
  })
  return { fetcher, calls }
}

describe('B1: the gate line', () => {
  it('names only what was worked out', () => {
    expect(gateLine({ videos: 5, lines: 11, est_usd: 0.42, est_s: 120, cap_usd: 2.5 })).toBe('5 videos · 11 lines · about $0.42 · about 2 min')
    expect(gateLine({ videos: 1, lines: null, est_usd: null, est_s: null, cap_usd: 0.5 })).toBe('1 video')
    expect(gateLine({ videos: 2, lines: 1, est_usd: 0.004, est_s: 40, cap_usd: 1 })).toBe('2 videos · 1 line · under $0.01 · about 40 s')
  })
})

describe('B1: Ask Voltage about all videos', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('picks every video by default, each with its stage, and plans the goal for the ones kept', async () => {
    const gate = batch('gate', [row(1, 'planned', 'Planned'), row(3, 'planned', 'Planned', { lines: null })], { totals: { videos: 2, lines: null, est_usd: null, est_s: null, cap_usd: 1 } })
    const { fetcher, calls } = server([[]], (method, url) => (url.endsWith('/projects/f1/batches') && method === 'POST' ? ok(gate, 201) : null))
    vi.stubGlobal('fetch', fetcher)
    render(<BatchPanel projectId="f1" videos={[video(1), video(2, 'approved'), video(3)]} />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading the last batch…')
    const picker = await screen.findByTestId('batch-picker')
    expect(within(picker).getAllByRole('checkbox').every((c) => (c as HTMLInputElement).checked)).toBe(true)
    expect(picker).toHaveTextContent('Approved')
    await userEvent.click(within(picker).getByRole('checkbox', { name: /ad2\.mp4/ }))
    expect(picker).toHaveTextContent('2 of 3 videos')
    await userEvent.click(screen.getByRole('button', { name: 'Plan it for 2 videos' }))
    expect(await screen.findByText('Say what you want done in the videos.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('What to change in every video'), 'Make it 30% off')
    await userEvent.click(screen.getByRole('button', { name: 'Plan it for 2 videos' }))
    expect(calls).toContain('POST /api/projects/f1/batches {"source":"ask","goal":"Make it 30% off","video_ids":["p1","p3"]}')
    const card = await screen.findByTestId('batch-gate')
    expect(within(card).getByTestId('batch-totals')).toHaveTextContent(/^2 videos$/)
    expect(within(card).getByTestId('batch-cap')).toHaveTextContent('Spends at most $1.00')
    expect(card).toHaveTextContent('Voltage decides')
    // The user's next action is last: Go.
    const buttons = within(card).getAllByRole('button')
    expect(buttons[buttons.length - 1]).toHaveTextContent('Go')
  })

  it('opens the gate with the totals, and Go starts the board', async () => {
    const gate = batch('gate', [row(1, 'planned', 'Planned'), row(2, 'planned', 'Planned'), row(3, 'planned', 'Planned', { lines: 2 })])
    const board = batch('running', [row(1, 'working', 'Working', { why: 'Voltage is on it' }), row(2, 'queued', 'Queued'), row(3, 'queued', 'Queued')])
    const { fetcher, calls } = server([[gate], [board]], (_method, url) => (url.endsWith('/batches/J9/go') ? ok(board, 202) : null))
    vi.stubGlobal('fetch', fetcher)
    render(<BatchPanel projectId="f1" videos={[video(1), video(2), video(3)]} />)
    expect(await screen.findByTestId('batch-totals')).toHaveTextContent('3 videos · 6 lines · about $0.42 · about 2 min')
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(calls).toContain('POST /api/projects/f1/batches/J9/go')
    const rows = await screen.findAllByTestId('batch-row')
    expect(rows.map((r) => r.getAttribute('data-state'))).toEqual(['working', 'queued', 'queued'])
    expect(screen.getByRole('button', { name: 'Cancel the rest' })).toBeInTheDocument()
    expect(within(rows[0]).getByRole('link', { name: 'ad1.mp4' })).toHaveAttribute('href', '#v/p1')
  })

  it('draws every row state, answers a paused video, adds all that passed and undoes one video', async () => {
    const rows = [
      row(1, 'ready', 'Ready to review', { why: '2 lines are ready to hear.', ready: 2, spent_usd: 0.05 }),
      row(2, 'nothing', 'Nothing to change', { why: 'Voltage found nothing to change here.' }),
      row(3, 'failed', 'Failed', { why: 'the model fell over' }),
      row(4, 'waiting', 'Waiting on you', { question: { text: 'Say 30% or 25%?', options: ['30%', '25%'] } }),
      row(5, 'cancelled', 'Cancelled', { why: 'Cancelled' }),
    ]
    const finished = batch('finished', rows)
    const added = batch('finished', [row(1, 'added', 'Added', { why: '2 lines added.', added: { edit_ids: ['e1', 'e2'], at: 'x', undone_at: null } }), ...rows.slice(1)])
    const undone = batch('finished', [row(1, 'ready', 'Ready to review', { ready: 2, added: { edit_ids: ['e1', 'e2'], at: 'x', undone_at: 'y' } }), ...rows.slice(1)])
    const { fetcher, calls } = server([[finished]], (_method, url) => {
      if (url.endsWith('/videos/p4/answer')) return ok(finished, 202)
      if (url.endsWith('/add-all')) return ok(added)
      if (url.endsWith('/videos/p1/undo-add')) return ok(undone)
      return null
    })
    vi.stubGlobal('fetch', fetcher)
    render(<BatchPanel projectId="f1" videos={[video(1), video(2), video(3), video(4), video(5)]} />)
    const board = await screen.findByTestId('batch-board')
    expect(within(board).getAllByTestId('batch-row').map((r) => r.getAttribute('data-state'))).toEqual(['ready', 'nothing', 'failed', 'waiting', 'cancelled'])
    expect(board).toHaveTextContent('Batch finished')
    expect(board).toHaveTextContent('the model fell over')
    const q = within(board).getByTestId('batch-question')
    expect(q).toHaveTextContent('Say 30% or 25%?')
    await userEvent.click(within(q).getByRole('button', { name: '30%' }))
    expect(calls).toContain('POST /api/projects/f1/batches/J9/videos/p4/answer {"text":"30%"}')
    await userEvent.click(within(board).getByRole('button', { name: 'Add all that passed · 1 video' }))
    expect(calls).toContain('POST /api/projects/f1/batches/J9/add-all')
    await userEvent.click(await screen.findByRole('button', { name: 'Undo the 2 lines added here' }))
    expect(calls).toContain('POST /api/projects/f1/batches/J9/videos/p1/undo-add')
    expect(await screen.findByText('Undone. The lines are back as proposals.')).toBeInTheDocument()
  })

  it('says why a plan was refused, and shows an empty project and a read error', async () => {
    const { fetcher } = server([[]], (method, url) => (url.endsWith('/projects/f1/batches') && method === 'POST'
      ? fail('This batch may spend up to $1.50, which would take Spring past its $0.05 project ceiling ($0.00 spent). Raise the ceiling on the project page, or pick fewer videos.') : null))
    vi.stubGlobal('fetch', fetcher)
    const { unmount } = render(<BatchPanel projectId="f1" videos={[video(1)]} />)
    await userEvent.type(await screen.findByLabelText('What to change in every video'), 'Make it 30% off')
    await userEvent.click(screen.getByRole('button', { name: 'Plan it for 1 video' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('$0.05 project ceiling')
    unmount()
    render(<BatchPanel projectId="f1" videos={[]} />)
    expect(await screen.findByTestId('batch-empty')).toHaveTextContent('Add videos to this project')
  })

  it('a read failure offers Try again', async () => {
    let first = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/me/onboarding')) return ok({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-batch'], checklist: [], checklist_hidden: true })
      if (url.endsWith('/me/flags')) return ok({ flags: ['projects.batch'] })
      if (first) { first = false; return fail('Server down', 500) }
      return ok({ batches: [] })
    }))
    render(<BatchPanel projectId="f1" videos={[video(1)]} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server down')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByTestId('batch-picker')).toBeInTheDocument()
  })

  it('a Fix in all from the check plans that issue across its videos', async () => {
    const gate = batch('gate', [row(1, 'planned', 'Planned')], { source: 'fix', goal: 'Two prices disagree.' })
    const { fetcher, calls } = server([[], [gate]], (method, url) => (url.endsWith('/projects/f1/batches') && method === 'POST' ? ok(gate, 201) : null))
    vi.stubGlobal('fetch', fetcher)
    const handled = vi.fn()
    render(<BatchPanel projectId="f1" videos={[video(1), video(2)]} fix={{ issueId: 4, message: 'Two prices disagree.', videoIds: ['p1', 'p2'] }} onFixHandled={handled} />)
    expect(await screen.findByTestId('batch-gate')).toHaveTextContent('Fix: Two prices disagree.')
    expect(calls).toContain('POST /api/projects/f1/batches {"source":"fix","issue_id":4,"video_ids":["p1","p2"]}')
    expect(handled).toHaveBeenCalled()
  })
})
