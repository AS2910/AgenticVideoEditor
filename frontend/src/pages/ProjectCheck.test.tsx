import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectCheck } from './ProjectCheck'
import { costWord } from '../lib/check'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const estimate = (available = true) => ({ usd: 0.004, label: 'about $0.01', input_tokens: 2400, output_tokens: 400, model: 'claude-haiku-4-5', available, why: available ? null : 'No Claude key is set.' })
const issue = (issue_id: number, kind: string, message: string, places: { video_id: string; filename: string; t: number | null; text: string }[], ignored = false) =>
  ({ issue_id, kind, message, places, fingerprint: `fp${issue_id}`, ignored })
const done = (over: Record<string, unknown> = {}) => ({ check_id: 1, project_id: 'f1', mode: 'rules', status: 'done', job_id: 'J1', trigger: 'user', cost_usd: 0, notes: [], error: null, started_at: '2026-10-21T10:00:00Z', finished_at: new Date(Date.now() - 120_000).toISOString(), ...over })

function server(pages: unknown[], extra: (method: string, url: string) => Response | null = () => null) {
  const calls: string[] = []
  let k = 0
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push(`${method} ${url}${init?.body ? ` ${init.body}` : ''}`)
    if (url.endsWith('/me/onboarding')) return ok({ tour: { step: 0, finished: true, skipped: true }, tips: ['first-project-check'], checklist: [], checklist_hidden: true })
    const other = extra(method, url)
    if (other) return other
    if (url.endsWith('/projects/f1/check') && method === 'GET') return ok(pages[Math.min(k++, pages.length - 1)])
    throw new Error(`unexpected ${method} ${url}`)
  })
  return { fetcher, calls }
}

describe('A2: the project check panel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the price before running, a Rules only option, and starts a check', async () => {
    const never = { check: null, issues: [], estimate: estimate(), fix_run: null, videos: 3 }
    const { fetcher, calls } = server([never], (method, url) => (url.endsWith('/projects/f1/check') && method === 'POST'
      ? ok({ ...never, check: done({ status: 'running', mode: 'full', finished_at: null, job: { step_label: 'Reading what the videos say' } }) }, 202) : null))
    vi.stubGlobal('fetch', fetcher)
    render(<ProjectCheck projectId="f1" />)
    expect(screen.getByRole('status')).toHaveTextContent('Reading the last check…')
    expect(await screen.findByText(/Not checked yet/)).toBeInTheDocument()
    expect(screen.getByTestId('check-cost')).toHaveTextContent('The rule checks are free; the text pass reads the transcripts for about $0.01.')
    expect(screen.getByRole('button', { name: 'Rules only' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Check project · about $0.01' }))
    expect(calls).toContain('POST /api/projects/f1/check {"mode":"full"}')
  })

  it('runs Rules only when there is no Claude key, and says so', async () => {
    const { fetcher, calls } = server([{ check: null, issues: [], estimate: estimate(false), fix_run: null, videos: 2 }],
      (method, url) => (url.endsWith('/projects/f1/check') && method === 'POST' ? ok({ check: null, issues: [], estimate: estimate(false), fix_run: null, videos: 2 }, 202) : null))
    vi.stubGlobal('fetch', fetcher)
    render(<ProjectCheck projectId="f1" />)
    expect(await screen.findByText('Rule checks only, free. No Claude key is set for the text pass.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rules only' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Check project' }))
    expect(calls).toContain('POST /api/projects/f1/check {"mode":"rules"}')
  })

  it('names each issue with its videos and times, links into the editor, and ignores one', async () => {
    const fact = issue(4, 'fact', 'The videos give different percentages: 20% in a.mp4; 30% in b.mp4.', [
      { video_id: 'p1', filename: 'a.mp4', t: 3.2, text: 'Get 20% off.' }, { video_id: 'p2', filename: 'b.mp4', t: 61, text: 'Get 30% off.' }])
    const line = issue(5, 'required_line', '“T&C apply” is a required line, and b.mp4 does not say it.', [{ video_id: 'p2', filename: 'b.mp4', t: null, text: '' }])
    const first = { check: done({ notes: ['Loudness not checked for c.mp4: no render measured yet.'] }), issues: [fact, line], estimate: estimate(), fix_run: null, videos: 3 }
    const after = { ...first, issues: [fact, { ...line, ignored: true }] }
    const { fetcher, calls } = server([first, after], (_method, url) => (url.endsWith('/issues/5/ignore') ? ok(after) : null))
    vi.stubGlobal('fetch', fetcher)
    render(<ProjectCheck projectId="f1" />)
    const issues = await screen.findAllByTestId('check-issue')
    expect(issues).toHaveLength(2)
    expect(screen.getByText('2 issues')).toBeInTheDocument()
    expect(screen.getByTestId('check-when')).toHaveTextContent('Checked 2 minutes ago, rule checks only, free.')
    expect(screen.getByText('Loudness not checked for c.mp4: no render measured yet.')).toBeInTheDocument()
    const places = within(issues[0]).getAllByTestId('check-place')
    expect(within(places[0]).getByRole('link')).toHaveAttribute('href', '#v/p1@3.2')
    expect(within(places[1]).getByRole('link')).toHaveTextContent('b.mp4 · 1:01')
    expect(within(issues[0]).getByRole('button', { name: 'Fix in all 2' })).toBeInTheDocument()
    expect(within(issues[1]).queryByRole('button', { name: /Fix in all/ })).toBeNull()
    await userEvent.click(within(issues[1]).getByRole('button', { name: 'Ignore' }))
    expect(calls.some((c) => c.startsWith('POST /api/projects/f1/check/issues/5/ignore'))).toBe(true)
    await waitFor(() => expect(screen.getAllByTestId('check-issue')).toHaveLength(1))
    await userEvent.click(screen.getByRole('button', { name: '1 ignored issue · Show' }))
    expect(screen.getByTestId('check-ignored')).toHaveTextContent('It comes back if these words change.')
  })

  it('says No issues found with when it ran, and a failed run offers Try again', async () => {
    const clean = { check: done({ mode: 'full', cost_usd: 0.0019 }), issues: [], estimate: estimate(), fix_run: null, videos: 2 }
    const { fetcher } = server([clean])
    vi.stubGlobal('fetch', fetcher)
    const { unmount } = render(<ProjectCheck projectId="f1" />)
    expect(await screen.findByText('No issues found')).toBeInTheDocument()
    expect(screen.getByTestId('check-when')).toHaveTextContent('Checked 2 minutes ago, with the text pass, under $0.01.')
    unmount()
    const failed = { check: done({ status: 'failed', error: 'boom', job: { error_text: 'The check stopped: boom' } }), issues: [], estimate: estimate(), fix_run: null, videos: 2 }
    vi.stubGlobal('fetch', server([failed]).fetcher)
    render(<ProjectCheck projectId="f1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The check stopped: boom')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('shows a run in progress and a read that failed', async () => {
    const working = { check: done({ status: 'running', finished_at: null, job: { step_label: 'Reading the videos' } }), issues: [], estimate: estimate(), fix_run: null, videos: 2 }
    vi.stubGlobal('fetch', server([working]).fetcher)
    const { unmount } = render(<ProjectCheck projectId="f1" />)
    expect(await screen.findByTestId('check-running')).toHaveTextContent('Reading the videos')
    expect(screen.getByRole('button', { name: /Check project/ })).toBeDisabled()
    unmount()
    vi.stubGlobal('fetch', server([], (_method, url) => (url.endsWith('/projects/f1/check') ? ok({ detail: 'nope' }, 500) : null)).fetcher)
    render(<ProjectCheck projectId="f1" />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('words a run\'s cost without inventing one', () => {
    expect(costWord('rules', 0)).toBe('rule checks only, free')
    expect(costWord('full', 0.0019)).toBe('with the text pass, under $0.01')
    expect(costWord('full', 0.034)).toBe('with the text pass, $0.03')
  })
})
