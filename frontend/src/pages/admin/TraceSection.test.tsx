import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TraceSection } from './TraceSection'
import { CloningControls } from './CloningControls'
import { ADMIN_SECTIONS } from './sections'
import { openTrace } from './traceApi'
import type { CloningState, Trace } from './traceApi'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response

const TRACE: Trace = {
  ref: 've_1a2b3c', found_by: 'export', abuse_report: null,
  exports: [{ mark: '129a9e7d036e0a1c', export_id: 've_1a2b3c', owner: 'acct:7', video_id: 'p1', file: 'ad-voltage.mp4', sha256: 'abc',
    created_at: '2026-10-31T10:00:00Z', export_attestation_id: 'ea_1', ai_voice: true, label_on: true, voices: ['v-clone'], takes: ['c1'] }],
  export_attestations: [{ id: 'ea_1', export_id: 'ex_9', owner: 'acct:7', voices_used: ['v-clone'], covers: ['p1:h'], statement_version: '2026-10-31',
    label_on: true, created_at: '2026-10-31T09:59:00Z', ip: '10.0.0.4' }],
  voices: [{ voice_id: 'v-clone', owner: 'acct:7', kind: 'cloned', scope: 'video', status: 'active', source_video_id: 'p1', speaker_label: '_', speaker_name: 'Asha',
    attestations: [{ id: 'va_1', owner: 'acct:7', video_id: 'p1', voice_id: 'v-clone', speaker_label: '_', choice: 'have_permission',
      statement_version: '2026-10-31', created_at: '2026-10-31T09:00:00Z', ip: '10.0.0.4', user_agent: 'x' }] }],
  synthesis: [{ id: 'sl_1', owner: 'acct:7', video_id: 'p1', voice_id: 'v-clone', attestation_id: 'va_1', line_check_id: 'lc_1', take_id: 'c1', cost_usd: 0.004, created_at: '2026-10-31T09:01:00Z' }],
  line_checks: [{ id: 'lc_1', voice_id: 'v-clone', text: null, verdict: 'pass', categories: [], model: 'claude-haiku-5-5', rule_hits: [], created_at: '2026-10-31T09:01:00Z' }],
  users: [{ owner: 'acct:7', emails: ['asha@example.com'], suspended: null, limits: { day: 5, month: 30 } }],
}

describe('Voice consent V1, step 7: Trace', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is a section of the admin page', () => {
    expect(ADMIN_SECTIONS.map((s) => s.id)).toContain('trace')
  })

  it('traces an export: the voice, its attestation, the confirmation, the lines and the person', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { urls.push(url); return ok(TRACE) }))
    render(<TraceSection card="" />)
    const go = screen.getByRole('button', { name: 'Trace' })
    expect(go).toBeDisabled()
    expect(screen.getByText('Each Trace is kept in the audit trail, since it shows personal data.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Export id, mark or abuse report number'), 've_1a2b3c')
    await userEvent.click(go)
    const result = await screen.findByTestId('trace-result')
    expect(urls).toEqual(['/api/admin/exports/ve_1a2b3c/trace'])
    expect(within(result).getByText('Found by its export id')).toBeInTheDocument()
    expect(within(result).getByTestId('trace-users')).toHaveTextContent('asha@example.com')
    expect(within(result).getByTestId('trace-users')).toHaveTextContent('Cloning allowed · 5 a day, 30 in 30 days')
    expect(within(result).getByTestId('trace-exports')).toHaveTextContent('ve_1a2b3c · mark 129a9e7d036e0a1c')
    expect(within(result).getByTestId('trace-exports')).toHaveTextContent('AI voice Label on')
    const voices = within(result).getByTestId('trace-voices')
    expect(voices).toHaveTextContent('Asha v-clone')
    expect(voices).toHaveTextContent('This video only')
    expect(voices).toHaveTextContent('I have permission from this person · statement 2026-10-31')
    expect(within(result).getByTestId('trace-confirmations')).toHaveTextContent('1 voice · label on · statement 2026-10-31 · 10.0.0.4')
    const line = within(result).getByTestId('trace-line')
    expect(line).toHaveTextContent('Passed take c1')
    expect(line).toHaveTextContent('$0.004')
  })

  it('says so when nothing matches', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ok({ detail: 'Nothing matches that. Check the export id, mark or report number.' }, 404)))
    render(<TraceSection card="" />)
    await userEvent.type(screen.getByLabelText('Export id, mark or abuse report number'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Trace' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing matches that. Check the export id, mark or report number.')
  })

  it('an abuse report Trace link fills it in and runs it', async () => {
    const urls: string[] = []
    const fromReport: Trace = { ...TRACE, found_by: 'abuse_report', ref: '42',
      abuse_report: { id: 42, location: 'https://x.example/v', kind: 'impersonation', details: 'Not me', contact: '', created_at: '' } }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { urls.push(url); return ok(fromReport) }))
    render(<TraceSection card="" />)
    act(() => openTrace('42'))
    expect(await screen.findByTestId('trace-report')).toHaveTextContent('Abuse report #42')
    expect(screen.getByLabelText('Export id, mark or abuse report number')).toHaveValue('42')
    expect(urls).toEqual(['/api/admin/exports/42/trace'])
  })
})

const STATE: CloningState = {
  owner: 'acct:7', suspended: null, enabled: true, limits: { day: 5, month: 30 }, used: { day: 1, month: 3 },
  voices: { active: 2, suspended: 0, withdrawn: 1 },
}

describe('Voice consent V1, step 7: suspend cloning and restore on a person', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the state, suspends with a reason, then restores with a reason', async () => {
    const calls: string[] = []
    let state: CloningState = { ...STATE }
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.endsWith('/suspend-cloning')) {
        state = { ...state, suspended: { reason: 'Report 42', by: 'acct:1', at: '2026-10-31T11:00:00Z' }, voices: { active: 0, suspended: 2, withdrawn: 1 } }
        return ok({ voices_disabled: 2 })
      }
      if (url.endsWith('/restore-cloning')) { state = { ...STATE }; return ok({ voices_restored: 2 }) }
      return ok(state)
    }))
    render(<CloningControls owner="acct:7" />)
    const box = await screen.findByTestId('user-cloning')
    expect(box).toHaveTextContent('Cloning allowed')
    expect(box).toHaveTextContent('Limits 5 a day, 30 in 30 days · used 1 today, 3 in 30 days')
    expect(box).toHaveTextContent('Cloned voices: 2 working, 0 suspended, 1 withdrawn')
    const suspend = within(box).getByRole('form', { name: 'Suspend cloning' })
    expect(within(suspend).getByRole('button', { name: 'Suspend cloning' })).toBeDisabled()
    await userEvent.type(within(suspend).getByLabelText('Why'), 'Report 42')
    await userEvent.click(within(suspend).getByRole('button', { name: 'Suspend cloning' }))
    expect(await screen.findByTestId('cloning-suspended')).toHaveTextContent('Cloning suspended')
    expect(calls).toContain('POST /api/admin/users/acct%3A7/suspend-cloning {"reason":"Report 42"}')
    expect(screen.getByTestId('user-cloning')).toHaveTextContent('by acct:1: Report 42')
    const restore = screen.getByRole('form', { name: 'Restore cloning' })
    expect(within(restore).getByRole('button', { name: 'Restore cloning' })).toBeDisabled()
    await userEvent.type(within(restore).getByLabelText('Why'), 'cleared')
    await userEvent.click(within(restore).getByRole('button', { name: 'Restore cloning' }))
    expect(await screen.findByRole('form', { name: 'Suspend cloning' })).toBeInTheDocument()
    expect(calls).toContain('POST /api/admin/users/acct%3A7/restore-cloning {"reason":"cleared"}')
  })

  it('changes the clone limits with a reason', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      return ok(url.endsWith('/clone-limits') ? { day: 9, month: 40 } : STATE)
    }))
    render(<CloningControls owner="acct:7" />)
    const form = await screen.findByRole('form', { name: 'Change limits' })
    const day = within(form).getByLabelText('A day')
    await userEvent.clear(day)
    await userEvent.type(day, '9')
    await userEvent.type(within(form).getByLabelText('Why'), 'an agency')
    await userEvent.click(within(form).getByRole('button', { name: 'Change limits' }))
    await vi.waitFor(() => expect(calls).toContain('POST /api/admin/users/acct%3A7/clone-limits {"day":9,"month":30,"reason":"an agency"}'))
  })

  it('is hidden while the voice checks are off for the person', async () => {
    const fetcher = vi.fn(async () => ok({ ...STATE, enabled: false }))
    vi.stubGlobal('fetch', fetcher)
    render(<CloningControls owner="acct:7" />)
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalled())
    expect(screen.queryByTestId('user-cloning')).not.toBeInTheDocument()
  })
})
