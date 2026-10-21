import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LinkImport } from './LinkImport'

const ok = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) }) as Response
const SOURCES = { sources: [{ name: 'drive', label: 'Google Drive', enabled: true, why_off: null }, { name: 'dropbox', label: 'Dropbox', enabled: true, why_off: null },
  { name: 'youtube', label: 'YouTube', enabled: false, why_off: 'Not set up yet.' }], max_bytes: 2147483648 }
const JOB = (extra: Record<string, unknown> = {}) => ({ job_id: 'J7', video_id: 'user-local', kind: 'import', status: 'running', step_label: 'Downloading from Dropbox', progress: 0.5,
  line_ids: [], created_at: '', started_at: '', finished_at: null, eta_s: null, error_code: null, error_text: null, cost_usd: null, retryable: false,
  detail: { source: 'dropbox', bytes: 50 * 1024 ** 2, total_bytes: 100 * 1024 ** 2 }, ...extra })

describe('G1: import from a link', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('starts the import into the chosen project, shows how far it is, then opens the video', async () => {
    const calls: string[] = []
    let polls = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`.trim())
      if (url.endsWith('/imports/sources')) return ok(SOURCES)
      if (url.endsWith('/imports')) return ok(JOB(), 202)
      polls += 1
      return ok(polls < 2 ? JOB() : JOB({ status: 'done', step_label: 'Ready', progress: 1, detail: { video_id: 'p9' } }))
    }))
    const onDone = vi.fn()
    render(<LinkImport projectId="f1" onDone={onDone} />)
    expect(await screen.findByText(/YouTube is not available yet\./)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Or paste a link'), 'https://www.dropbox.com/s/abc/ad.mp4')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByTestId('import-progress')).toHaveTextContent('Downloading from Dropbox, 50 MB of 100 MB.')
    expect(screen.getByRole('button', { name: 'Importing…' })).toBeDisabled()
    expect(calls).toContain('POST /api/imports {"url":"https://www.dropbox.com/s/abc/ad.mp4","project_id":"f1"}')
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('p9'), { timeout: 4000 })
  })

  it('says why a link is refused, and why a running import failed', async () => {
    let refuse = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/imports/sources')) return ok(SOURCES)
      if (url.endsWith('/imports')) return refuse ? ok({ detail: 'Paste a share link from Google Drive or Dropbox.' }, 422) : ok(JOB(), 202)
      return ok(JOB({ status: 'failed', error_text: 'That link opens a page on Dropbox, not a video file.' }))
    }))
    render(<LinkImport projectId={null} onDone={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Or paste a link'), 'https://example.com/a')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Paste a share link from Google Drive or Dropbox.')
    refuse = false
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('That link opens a page on Dropbox, not a video file.'), { timeout: 4000 })
  })
})
